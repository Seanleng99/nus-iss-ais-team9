"""Keep the real AI tests covered once across agent workflows and general CI."""

import ast
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

import pytest

from infra.scripts.check_test_ownership import validate_ownership

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
    "platform",
}


def test_manifest_exposes_agent_platform_and_shared_ownership():
    assert set(MANIFEST["suites"]) == EXPECTED_SUITES
    catalog = json.loads(runner.REPOSITORY_ROOT.joinpath(
        "infra/llmsecops/agent-evaluation-specs.json",
    ).read_text(encoding="utf-8"))
    assert set(catalog["suites"]) == EXPECTED_SUITES
    assert "ci_only_test_paths" not in MANIFEST
    assert catalog["shared"]["test_selection"] == MANIFEST["shared"]
    assert "tests/test_conversational_pipeline.py" in MANIFEST["suites"]["orchestrator"]["test_paths"]


def test_every_test_module_has_explicit_package_ownership():
    for package, selections in (("ai-service", MANIFEST["suites"].values()), ("shared", [MANIFEST["shared"]])):
        root = REPOSITORY_ROOT / "apps" / package
        discovered = {path.relative_to(root).as_posix() for pattern in ("test_*.py", "*_test.py")
                      for path in (root / "tests").rglob(pattern)}
        declared = {path for selection in selections for path in selection["test_paths"]}
        assert declared == discovered
    with pytest.raises(KeyError):
        runner.pytest_arguments("remaining", MANIFEST)


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
    prefixes = [selection["name_prefix"] for selection in MANIFEST["suites"].values()
                if "name_prefix" in selection]
    assert len(prefixes) == len(set(prefixes)) == 7
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


def test_collected_parameterized_cases_have_disjoint_exact_function_owners():
    nodes = ["tests/test_examples.py::test_budget[x]", "tests/test_examples.py::test_goal[y]"]
    report = validate_ownership(nodes, {
        "budget": ["tests/test_examples.py::test_budget"],
        "goal": ["tests/test_examples.py::test_goal"],
    }, {"tests/test_examples.py"})
    assert report["passed"] and report["owner_counts"] == {"budget": 1, "goal": 1}


@pytest.mark.parametrize("nodes,selections,files", [
    (["tests/test_a.py::test_one"], {"budget": ["tests/test_b.py"]}, {"tests/test_a.py"}),
    (["tests/test_a.py::test_one"], {"budget": ["tests/test_a.py"], "goal": ["tests/test_a.py::test_one"]}, {"tests/test_a.py"}),
    (["tests/test_a.py::test_one"], {"budget": ["tests/test_a.py", "tests/test_a.py"]}, {"tests/test_a.py"}),
    (["tests/test_a.py::test_one_extra"], {"budget": ["tests/test_a.py::test_one"]}, {"tests/test_a.py"}),
    (["tests/test_a.py::test_one"], {"budget": ["tests/test_a.py"]}, {"tests/test_a.py", "tests/test_empty.py"}),
    (["tests/test_a.py::test_one"] * 2, {"budget": ["tests/test_a.py"]}, {"tests/test_a.py"}),
    ([], {"budget": []}, set()),
    (["tests/test_a.py::test_one"], {"budget": ["tests/../test_a.py"]}, {"tests/test_a.py"}),
])
def test_new_missing_overlapping_or_empty_ownership_fails(nodes, selections, files):
    report = validate_ownership(nodes, selections, files)
    assert not report["passed"] and report["errors"]


def test_shared_runner_selects_explicit_library_files():
    assert runner.pytest_arguments("shared", MANIFEST) == MANIFEST["shared"]["test_paths"]
