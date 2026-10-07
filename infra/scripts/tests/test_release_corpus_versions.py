"""Run the release's version loading and task verification without AWS."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
STEPS = {step.get("name"): step for step in WORKFLOW["jobs"]["deploy-demo"]["steps"]}


def run_step(name, cwd, env):
    # Use Git Bash on Windows; the system bash launcher can resolve to WSL.
    bash = "bash"
    if os.name == "nt":
        git = Path(shutil.which("git"))
        bash = str(git.parent.parent / "bin" / "bash.exe")
    return subprocess.run(
        [bash, "-eu", "-o", "pipefail", "-c", STEPS[name]["run"].replace("${{ github.sha }}", "0123456789abcdef0123456789abcdef01234567")],
        cwd=cwd,
        env={**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"], **env},
        capture_output=True, text=True, timeout=30, check=False,
    )


def load_versions(tmp_path, education="investment-education-sg@next", policy="financial-coach-policy-sg@next"):
    for directory, version in (("investment_education", education), ("policy_controls", policy)):
        path = tmp_path / "knowledge" / directory / "source_manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"corpus_version": version}))
    output = tmp_path / "github-env"
    result = run_step("Load packaged corpus versions", tmp_path, {"GITHUB_ENV": str(output)})
    values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    return result, values


def test_release_replaces_stale_task_pins_and_checks_the_rendered_versions(tmp_path):
    result, values = load_versions(tmp_path)
    assert result.returncode == 0, result.stderr
    assert values == {
        "EDUCATION_CORPUS_VERSION": "investment-education-sg@next",
        "POLICY_CORPUS_VERSION": "financial-coach-policy-sg@next",
    }
    environment = {**dict.fromkeys(values, "stale-corpus@old"), "MAX_MODEL_TOKENS_PER_RUN": "40000"}
    role_output = tmp_path / "role-env"
    loaded = run_step("Load AI role policy", ROOT, {"GITHUB_ENV": str(role_output)})
    assert loaded.returncode == 0, loaded.stderr
    values.update(dict(line.split("=", 1) for line in role_output.read_text().splitlines()))
    environment["MODEL_ROLE_OVERRIDES"] = '{}'
    rendered = STEPS["Render AI service task definition"]["with"]["environment-variables"]
    rendered = rendered.replace("${{ github.sha }}", "0123456789abcdef0123456789abcdef01234567")
    rendered = re.sub(r"\$\{\{ env\.(\w+) \}\}", lambda match: values[match[1]], rendered)
    environment.update(line.split("=", 1) for line in rendered.strip().splitlines())
    assert environment["MAX_MODEL_TOKENS_PER_RUN"] == "80000"
    assert environment["PROMPT_SET_VERSION"] == values["PROMPT_SET_VERSION"]
    assert json.loads(environment["MODEL_ROLE_OVERRIDES"])["risk_compliance"] == {
        "reasoning_effort": "medium", "max_tokens": 3000,
    }
    task = {"containerDefinitions": [{
        "name": "ai-service",
        "environment": [{"name": key, "value": value} for key, value in environment.items()],
        "secrets": [{"name": "OPENAI_API_KEY", "valueFrom": "synthetic-secret-reference"}],
    }]}
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task))
    env = {**values, "RENDERED_AI_TASK": str(path), "AI_CONTAINER_NAME": "ai-service"}
    verified = run_step("Verify AI runtime configuration has not drifted", ROOT, env)
    assert verified.returncode == 0, verified.stderr + verified.stdout
    for pin in [*values, "MAX_MODEL_TOKENS_PER_RUN", "MODEL_REASONING_EFFORT",
                "MODEL_MAX_TOKENS", "PROMPT_SET_VERSION"]:
        item = next(item for item in task["containerDefinitions"][0]["environment"] if item["name"] == pin)
        expected_value = item["value"]
        item["value"] = ("40000" if pin == "MAX_MODEL_TOKENS_PER_RUN" else
                         '{}' if pin == "MODEL_ROLE_OVERRIDES" else "stale-corpus@old")
        path.write_text(json.dumps(task))
        rejected = run_step("Verify AI runtime configuration has not drifted", ROOT, env)
        assert rejected.returncode != 0
        assert pin in rejected.stderr + rejected.stdout
        item["value"] = expected_value
    smoke = STEPS["Run health and AI safety smoke tests"]["run"]
    assert '--expected-corpus-version "$EDUCATION_CORPUS_VERSION"' in smoke
    assert '--expected-policy-corpus-version "$POLICY_CORPUS_VERSION"' in smoke


@pytest.mark.parametrize("invalid", [None, 42, "", "x\nINJECTED=value", "investment-education-sg@local-fixture-v1"])
def test_invalid_corpus_version_cannot_be_published_to_github_environment(tmp_path, invalid):
    result, values = load_versions(tmp_path, policy=invalid)
    assert result.returncode != 0
    assert values == {}


def test_bootstrap_and_live_evaluation_pins_match_packaged_manifests():
    versions = {
        name: json.loads((ROOT / "knowledge" / directory / "source_manifest.json").read_text())["corpus_version"]
        for name, directory in (("Education", "investment_education"), ("Policy", "policy_controls"))
    }
    template = yaml.load((ROOT / "infra/aws/demo-application.yaml").read_text(), Loader=yaml.BaseLoader)
    bootstrap = (ROOT / "infra/scripts/bootstrap_demo.ps1").read_text()
    for name, version in versions.items():
        assert template["Parameters"][f"{name}CorpusVersion"]["Default"] == version
        default = re.search(rf'\$\b{name}CorpusVersion = "([^"]+)"', bootstrap)
        assert default and default[1] == version
    cases = [json.loads(line) for line in (ROOT / "infra/llmsecops/live-evaluation-cases.jsonl").read_text().splitlines()]
    for key, name in (("retrieval_corpus_version", "Education"), ("policy_corpus_version", "Policy")):
        pins = [case["expected"][key] for case in cases if key in case["expected"]]
        assert pins and set(pins) == {versions[name]}
