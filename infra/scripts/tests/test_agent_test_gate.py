"""Exercise the CI agent gate without GitHub, paid models, or AWS credentials."""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

RESULTS = ("OFFLINE_RESULT", "METRICS_RESULT")


def run_gate(tmp_path, *, ai_ci="true", deploy="false", changes="success", **results):
    bash = shutil.which("bash")
    if os.name == "nt":
        # Prefer Git Bash over Windows' bash.exe, which launches WSL.
        git = shutil.which("git")
        candidate = Path(git).parents[1] / "bin/bash.exe" if git else None
        if candidate is None or not candidate.is_file():
            pytest.skip("CI shell gate requires Git Bash on Windows")
        bash = str(candidate)
    if not bash:
        pytest.skip("CI gate requires bash")
    workflow = Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml"
    source = workflow.read_text(encoding="utf-8").split(
        "name: Require every selected agent suite to pass", 1,
    )[1]
    script = textwrap.dedent(source.split("        run: |\n", 1)[1].split(
        "\n  ai-service:", 1,
    )[0])
    env = {
        **os.environ,
        **dict.fromkeys(RESULTS, "success"),
        **results,
        "AI_CI": ai_ci,
        "DEPLOY": deploy,
        "CHANGES_RESULT": changes,
        "GITHUB_STEP_SUMMARY": (tmp_path / "summary.md").as_posix(),
    }
    return subprocess.run(
        [bash, "-eu", "-c", script], env=env, capture_output=True,
        text=True, timeout=10, check=False,
    )


@pytest.mark.parametrize("agent", RESULTS)
@pytest.mark.parametrize("result", ("failure", "cancelled", "skipped"))
def test_required_suite_must_pass(tmp_path, agent, result):
    outcome = run_gate(tmp_path, **{agent: result})
    assert outcome.returncode != 0
    assert "Agent suites or metrics did not pass" in outcome.stderr


def test_all_successful_suites_pass(tmp_path):
    outcome = run_gate(tmp_path)
    assert outcome.returncode == 0, outcome.stderr


def test_frontend_only_release_still_requires_agents(tmp_path):
    outcome = run_gate(tmp_path, ai_ci="false", deploy="true", OFFLINE_RESULT="skipped")
    assert outcome.returncode != 0


def test_non_ai_non_release_change_allows_skipped_suites(tmp_path):
    outcome = run_gate(tmp_path, ai_ci="false", deploy="false",
                       **dict.fromkeys(RESULTS, "skipped"))
    assert outcome.returncode == 0, outcome.stderr


@pytest.mark.parametrize("changes", ("failure", "cancelled", "skipped"))
def test_failed_change_detection_cannot_pass_the_gate(tmp_path, changes):
    assert run_gate(tmp_path, changes=changes).returncode != 0
