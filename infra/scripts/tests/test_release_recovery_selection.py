"""Exercise the real release-gate shell with a local GitHub stub, without AWS."""
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def run_gate(tmp_path, manifest, stale=False):
    if not shutil.which("bash") or not shutil.which("jq"):
        pytest.skip("Release gate requires bash and jq")
    workflow = Path(__file__).resolve().parents[3] / ".github/workflows/release.yml"
    source = workflow.read_text().split("name: Load change manifest and reject stale runs", 1)[1]
    script = textwrap.dedent(source.split("        run: |\n", 1)[1].split("\n  build-images:", 1)[0])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        '#!/bin/bash\nset -eu\n'
        'if [[ "$1" == "api" ]]; then printf "%s\\n" "$TEST_MAIN_SHA"; '
        'else cp "$TEST_MANIFEST" artifacts/change-manifest.json; fi\n'
    )
    gh.chmod(0o700)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "outputs"
    env = {
        **os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "GITHUB_REPOSITORY": "synthetic/recovery-test", "SOURCE_RUN_ID": "1",
        "RELEASE_SHA": "a" * 40, "TEST_MAIN_SHA": ("b" if stale else "a") * 40,
        "TEST_MANIFEST": str(manifest_path), "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        ["bash", "-eu", "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=10, check=False,
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    return result, values


@pytest.mark.parametrize("services", [("frontend",), ("backend",), ("ai", "backend")])
def test_recovery_releases_earlier_fixes_even_if_the_new_push_changed_one_service(tmp_path, services):
    manifest = {f"{name}_deploy": name in services for name in ("frontend", "backend", "ai")}
    manifest.update(deploy=True, migrations=False)
    result, values = run_gate(tmp_path, manifest)
    assert result.returncode == 0, result.stderr
    assert values == {key: "true" for key in ("frontend", "backend", "ai", "migrations", "deploy")}


def test_non_application_change_still_does_not_deploy(tmp_path):
    manifest = {key: False for key in ("frontend_deploy", "backend_deploy", "ai_deploy", "migrations", "deploy")}
    result, values = run_gate(tmp_path, manifest)
    assert result.returncode == 0, result.stderr
    assert set(values.values()) == {"false"}


def test_stale_run_cannot_trigger_recovery_deployment(tmp_path):
    result, values = run_gate(tmp_path, {}, stale=True)
    assert result.returncode == 0, result.stderr
    assert values == {"deploy": "false"}
