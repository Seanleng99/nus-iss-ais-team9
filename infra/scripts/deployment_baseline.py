"""Find the last completed application deployment, excluding green no-op releases."""

import argparse
import json
import re
import subprocess
from pathlib import Path


def github_json(path: str) -> dict:
    result = subprocess.run(
        ["gh", "api", path], check=True, capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def completed_step(job, names):
    return (job.get("conclusion") == "success"
            and any(step.get("name") in names and step.get("conclusion") == "success"
                    for step in job.get("steps", [])))


def accepted_deployment(jobs):
    deployed = next((job for job in jobs if job.get("name") == "Deploy demo environment"), {})
    if not completed_step(deployed, {
        "Deploy AI service", "Deploy application backend", "Deploy Streamlit frontend",
    }):
        return False
    # Retained releases from before the split have smoke inside the deployment job.
    split_gate = next((job for job in jobs if job.get("name") == "Require complete live release acceptance"), None)
    if split_gate is None:
        return completed_step(deployed, {"Run health and AI safety smoke tests"})
    smoke = next((job for job in jobs if job.get("name") == "Health and AI safety smoke"), {})
    return (completed_step(smoke, {"Run health and AI safety smoke tests"})
            and completed_step(split_gate, {"Require complete live release acceptance"}))


def last_deployment(repository: str, api=github_json) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    # Bounded history lookup. If retained history has no deployment, CI runs all checks.
    for page in range(1, 11):
        history = api(
            f"repos/{repository}/actions/workflows/release.yml/runs"
            f"?branch=main&status=success&per_page=100&page={page}"
        )["workflow_runs"]
        for run in history:
            if run.get("conclusion") != "success" or run.get("head_branch") != "main":
                continue
            jobs = api(f"repos/{repository}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
            if accepted_deployment(jobs):
                sha = run["head_sha"]
                if not re.fullmatch(r"[a-f0-9]{40}", sha):
                    raise ValueError("Invalid deployed commit SHA")
                return {"sha": sha, "run_id": run["id"]}
        if len(history) < 100:
            break
    return None


def comparison_baseline(deployment: dict | None, is_ancestor) -> dict:
    if deployment is None:
        return {"sha": "", "deployment": None, "reason": "no_successful_deployment"}
    if not is_ancestor(deployment["sha"]):
        return {"sha": "", "deployment": deployment, "reason": "deployment_outside_checkout_history"}
    return {"sha": deployment["sha"], "deployment": deployment, "reason": "successful_application_deployment"}


def checkout_contains(sha: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        check=False, capture_output=True, timeout=10,
    ).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    baseline = comparison_baseline(last_deployment(args.repository), checkout_contains)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    with args.github_output.open("a", encoding="utf-8") as output:
        output.write(f"sha={baseline['sha']}\n")
    print(json.dumps(baseline))


if __name__ == "__main__":
    main()
