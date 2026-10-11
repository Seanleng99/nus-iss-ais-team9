import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "deployment_baseline", Path(__file__).parents[1] / "deployment_baseline.py",
)
assert SPEC and SPEC.loader
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)

CHANGE_SPEC = importlib.util.spec_from_file_location(
    "detect_changes", Path(__file__).parents[1] / "detect_changes.py",
)
assert CHANGE_SPEC and CHANGE_SPEC.loader
changes = importlib.util.module_from_spec(CHANGE_SPEC)
CHANGE_SPEC.loader.exec_module(changes)


def run(run_id, sha="a" * 40, **overrides):
    return {"id": run_id, "head_sha": sha, "head_branch": "main", "conclusion": "success", **overrides}


def deployed_steps():
    return [{"name": name, "conclusion": "success"} for name in (
        "Deploy AI service", "Run health and AI safety smoke tests",
    )]


class DeploymentBaselineTests(unittest.TestCase):
    def test_split_deployment_advances_baseline_only_after_smoke_and_acceptance(self):
        jobs = [
            {"name": "Deploy demo environment", "conclusion": "success", "steps": [deployed_steps()[0]]},
            {"name": "Health and AI safety smoke", "conclusion": "success", "steps": [deployed_steps()[1]]},
            {"name": "Require complete live release acceptance", "conclusion": "success", "steps": [
                {"name": "Require complete live release acceptance", "conclusion": "success"}]},
        ]
        self.assertTrue(baseline.accepted_deployment(jobs))
        for index in range(3):
            for status in ("failure", "cancelled", "skipped"):
                with self.subTest(job=index, status=status):
                    self.assertFalse(baseline.accepted_deployment([
                        {**job, "conclusion": status} if position == index else job
                        for position, job in enumerate(jobs)]))
                    self.assertFalse(baseline.accepted_deployment([
                        {**job, "steps": [{**step, "conclusion": status} for step in job["steps"]]}
                        if position == index else job for position, job in enumerate(jobs)]))
            self.assertFalse(baseline.accepted_deployment(jobs[:index] + jobs[index + 1:]))

    def test_successful_superseded_job_with_skipped_deployment_cannot_advance_baseline(self):
        def api(path):
            if "/workflows/" in path:
                return {"workflow_runs": [run(2), run(1, "b" * 40)]}
            steps = deployed_steps()
            if "/runs/2/jobs" in path:
                steps = [{**step, "conclusion": "skipped"} for step in steps]
            return {"jobs": [{"name": "Deploy demo environment", "conclusion": "success", "steps": steps}]}

        self.assertEqual(baseline.last_deployment("team/coach", api), {"sha": "b" * 40, "run_id": 1})

    def test_security_followup_retains_application_changes_since_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.run(
                    ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=10,
                ).stdout.strip()

            def commit():
                git("add", ".")
                git("-c", "user.name=Synthetic CI Test", "-c", "user.email=ci@example.test",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic regression fixture")
                return git("rev-parse", "HEAD")

            git("init", "-q")
            runtime = root / "apps/ai-service/app/orchestrator.py"
            runtime.parent.mkdir(parents=True)
            runtime.write_text("# deployed version\n")
            deployed = commit()
            runtime.write_text("# pending application fix\n")
            previous_push = commit()
            security = root / "security/promptfoo/provider.py"
            security.parent.mkdir(parents=True)
            security.write_text("# security adapter followup\n")
            commit()
            newest = changes.classify_changes(git("diff", "--name-only", previous_push, "HEAD").splitlines())
            pending = changes.classify_changes(git("diff", "--name-only", deployed, "HEAD").splitlines())
            self.assertFalse(newest["deploy"])
            for flag in ("ai_ci", "backend_ci", "integration", "ai_deploy", "backend_deploy", "deploy"):
                self.assertTrue(pending[flag], flag)

    def test_green_noop_and_failed_deployment_do_not_hide_pending_application_changes(self):
        calls = []

        def api(path):
            calls.append(path)
            if "/workflows/" in path:
                return {"workflow_runs": [run(3), run(2), run(1, "b" * 40)]}
            conclusion = {3: "skipped", 2: "failure", 1: "success"}
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": [{"name": "Deploy demo environment", "conclusion": conclusion[run_id], "steps": deployed_steps()}]}

        self.assertEqual(baseline.last_deployment("team/coach", api), {"sha": "b" * 40, "run_id": 1})
        self.assertEqual(len(calls), 4)

    def test_failed_release_and_other_branch_cannot_advance_baseline(self):
        def api(path):
            if "/workflows/" in path:
                return {"workflow_runs": [run(3, conclusion="failure"), run(2, head_branch="feature"), run(1)]}
            self.assertIn("/runs/1/jobs", path)
            return {"jobs": [{"name": "Deploy demo environment", "conclusion": "success", "steps": deployed_steps()}]}

        self.assertEqual(baseline.last_deployment("team/coach", api), {"sha": "a" * 40, "run_id": 1})

    def test_no_retained_deployment_requires_complete_ci(self):
        self.assertIsNone(baseline.last_deployment("team/coach", lambda path: {"workflow_runs": []}))
        result = baseline.comparison_baseline(None, lambda sha: self.fail("No SHA to inspect"))
        self.assertEqual(result["sha"], "")

    def test_previous_page_is_checked_after_one_hundred_noop_releases(self):
        def api(path):
            if "/workflows/" in path:
                return {"workflow_runs": [run(index) for index in range(2, 102)] if path.endswith("&page=1") else [run(1)]}
            return {"jobs": [{"name": "Deploy demo environment", "conclusion":
                              "success" if "/runs/1/jobs" in path else "skipped", "steps": deployed_steps()}]}

        self.assertEqual(baseline.last_deployment("team/coach", api)["run_id"], 1)

    def test_rewritten_or_unavailable_checkout_history_requires_complete_ci(self):
        deployment = {"sha": "a" * 40, "run_id": 1}
        result = baseline.comparison_baseline(deployment, lambda sha: False)
        self.assertEqual(result["sha"], "")
        self.assertEqual(result["deployment"], deployment)
        self.assertEqual(baseline.comparison_baseline(deployment, lambda sha: True)["sha"], "a" * 40)

    def test_api_failure_stops_classification_instead_of_using_a_partial_baseline(self):
        def api(path):
            raise RuntimeError("Synthetic API failure")

        with self.assertRaises(RuntimeError):
            baseline.last_deployment("team/coach", api)

    def test_invalid_repository_or_deployed_sha_is_rejected(self):
        with self.assertRaises(ValueError):
            baseline.last_deployment("team/coach?extra=argument")

        def api(path):
            if "/workflows/" in path:
                return {"workflow_runs": [run(1, "invalid\nsha=value")]}
            return {"jobs": [{"name": "Deploy demo environment", "conclusion": "success", "steps": deployed_steps()}]}

        with self.assertRaises(ValueError):
            baseline.last_deployment("team/coach", api)


if __name__ == "__main__":
    unittest.main()
