"""Keep the real AI tests covered once across agent workflows and general CI."""

import ast
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "run_agent_tests", REPOSITORY_ROOT / "infra/scripts/run_agent_tests.py",
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
MANIFEST = json.loads(runner.MANIFEST_PATH.read_text(encoding="utf-8"))
EXPECTED_SUITES = {
    "orchestrator", "spending", "budget", "goal", "investment", "risk-compliance", "rag",
}


def test_manifest_exposes_exactly_the_seven_offline_jobs():
    assert set(MANIFEST["suites"]) == EXPECTED_SUITES
    catalog = json.loads(runner.REPOSITORY_ROOT.joinpath(
        "infra/llmsecops/agent-evaluation-specs.json",
    ).read_text(encoding="utf-8"))
    assert set(catalog["suites"]) == EXPECTED_SUITES
    assert set(MANIFEST["ci_only_test_paths"]) == {"tests/test_conversational_pipeline.py"}


def test_remaining_tests_exclude_exactly_the_paths_owned_by_other_jobs():
    owned = set(MANIFEST["ci_only_test_paths"])
    for selection in MANIFEST["suites"].values():
        owned.update(selection["test_paths"])
    args = runner.pytest_arguments("remaining", MANIFEST)
    assert args[0] == "tests"
    assert set(args[1:]) == {f"--ignore={path}" for path in owned}
    assert len(args[1:]) == len(owned)


def test_shared_files_have_one_full_owner_or_exhaustive_disjoint_prefix_groups():
    selections_by_path = defaultdict(list)
    for suite, selection in MANIFEST["suites"].items():
        prefix_path = selection.get("name_prefix_test_path")
        assert prefix_path is None or prefix_path in selection["test_paths"]
        for path in selection["test_paths"]:
            assert path.startswith("tests/") and path.endswith(".py")
            assert ".." not in Path(path).parts
            prefix = selection.get("name_prefix", "") if path == prefix_path else ""
            selections_by_path[path].append((suite, prefix))
    assert not set(MANIFEST["ci_only_test_paths"]) & selections_by_path.keys()
    for path, owners in selections_by_path.items():
        source = (REPOSITORY_ROOT / "apps/ai-service" / path).read_text(encoding="utf-8")
        names = [node.name for node in ast.walk(ast.parse(source))
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name.startswith("test_")]
        assert names, path
        for name in names:
            matches = [suite for suite, prefix in owners if not prefix or prefix in name]
            assert len(matches) == 1, (path, name, matches)
        for suite, prefix in owners:
            assert any(not prefix or prefix in name for name in names), suite


def test_offline_example_functions_have_one_suite_owner_each():
    path = "tests/test_agent_evaluation_examples.py"
    source = (REPOSITORY_ROOT / "apps/ai-service" / path).read_text(encoding="utf-8")
    names = {node.name for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}
    prefixes = [MANIFEST["suites"][suite]["name_prefix"] for suite in EXPECTED_SUITES]
    assert len(prefixes) == len(set(prefixes)) == len(EXPECTED_SUITES)
    assert {name for name in names if any(prefix in name for prefix in prefixes)} == names
    assert all(sum(prefix in name for prefix in prefixes) == 1 for name in names)


@pytest.mark.parametrize("suite", MANIFEST["suites"])
def test_agent_command_uses_its_owned_selection(suite):
    selection = MANIFEST["suites"][suite]
    args = runner.pytest_arguments(suite, MANIFEST)
    prefix_path = selection.get("name_prefix_test_path")
    expected = [path for path in selection["test_paths"] if path != prefix_path]
    if prefix_path:
        expected.append(f"{prefix_path}::{selection['name_prefix']}")
    elif selection.get("name_prefix"):
        expected.extend(["-k", selection["name_prefix"]])
    assert args == expected


def test_unknown_suite_cannot_silently_run_the_remaining_tests():
    with pytest.raises(KeyError):
        runner.pytest_arguments("unknown-agent", MANIFEST)
