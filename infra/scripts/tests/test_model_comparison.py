import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "model_comparison.py"
SPEC = importlib.util.spec_from_file_location("model_comparison", MODULE_PATH)
assert SPEC and SPEC.loader
model_comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_comparison)

REPO_ROOT = Path(__file__).parents[3]
POLICY_PATH = REPO_ROOT / "infra/llmsecops/model-comparison-policy.json"


def _report(role: str, model_id: str, failures: list[str]) -> dict:
    return {
        "role": role,
        "model_id": model_id,
        "gate_failures": failures,
    }


def test_policy_defines_one_baseline_and_a_lower_cost_candidate() -> None:
    policy = model_comparison.load_policy(POLICY_PATH)

    baseline = next(model for model in policy["models"] if model["role"] == "baseline")
    candidate = next(model for model in policy["models"] if model["role"] == "candidate")

    assert policy["comparison_id"] == "nova-lite-vs-nova-micro-v4-2026-08-31"
    assert policy["prompt_set_version"] == "v4"
    assert baseline["model_id"] == "apac.amazon.nova-lite-v1:0"
    assert candidate["model_id"] == "apac.amazon.nova-micro-v1:0"
    assert candidate["aws_region"] == "ap-southeast-1"
    assert candidate["invocation_type"] == "geo_inference_profile"
    assert candidate["input_cost_per_million"] < baseline["input_cost_per_million"]
    assert candidate["output_cost_per_million"] < baseline["output_cost_per_million"]
    assert baseline["pricing_checked_on"] == "2026-08-31"
    assert candidate["pricing_checked_on"] == "2026-08-31"


def test_case_set_covers_every_required_selection_category() -> None:
    policy = model_comparison.load_policy(POLICY_PATH)
    cases = model_comparison.load_cases(REPO_ROOT / policy["cases"])

    categories = {case["category"] for case in cases}

    assert categories == {"dependency", "fairness", "rag", "routing", "safety"}
    assert any(case.get("kind") == "fairness_pair" for case in cases)


def test_assessment_rejects_model_unavailable_from_required_region() -> None:
    selection = model_comparison.load_policy(POLICY_PATH)["selection"]
    report = {
        "catalog": {"verified": True},
        "entitlement_verified": True,
        "execution_error_count": 0,
        "aws_region": "ap-southeast-2",
        "deployment_source_regions": ["ap-southeast-2"],
        "geography": "APAC",
        "pass_rate": 1.0,
        "category_pass_rates": {
            category: 1.0
            for category in selection["minimum_category_pass_rates"]
        },
        "latency_ms": {"p95": 1000},
        "cost_estimate": {"estimated_total": 0.01},
    }

    failures = model_comparison.assess_model(report, selection)

    assert failures == ["REQUIRED_DEPLOYMENT_REGION_UNAVAILABLE"]


def test_assessment_rejects_incomplete_model_executions() -> None:
    selection = model_comparison.load_policy(POLICY_PATH)["selection"]
    report = {
        "catalog": {"verified": True},
        "entitlement_verified": True,
        "execution_error_count": 1,
        "aws_region": "ap-southeast-1",
        "deployment_source_regions": ["ap-southeast-1"],
        "geography": "APAC",
        "pass_rate": 1.0,
        "category_pass_rates": {
            category: 1.0
            for category in selection["minimum_category_pass_rates"]
        },
        "latency_ms": {"p95": 1000},
        "cost_estimate": {"estimated_total": 0.01},
    }

    failures = model_comparison.assess_model(report, selection)

    assert failures == ["EXECUTION_ERRORS_PRESENT"]


def test_selection_retains_baseline_when_candidate_is_ineligible() -> None:
    decision = model_comparison.select_model(
        [
            _report("baseline", "baseline", []),
            _report(
                "candidate",
                "candidate",
                ["REQUIRED_DEPLOYMENT_REGION_UNAVAILABLE"],
            ),
        ]
    )

    assert decision["status"] == "retain_baseline"
    assert decision["selected_model_id"] == "baseline"
    assert decision["human_review_required"] is False


def test_selection_requires_human_review_for_eligible_candidate() -> None:
    decision = model_comparison.select_model(
        [
            _report("baseline", "baseline", []),
            _report("candidate", "candidate", []),
        ]
    )

    assert decision["status"] == "pending_human_review"
    assert decision["selected_model_id"] == "baseline"
    assert decision["human_review_required"] is True


def test_human_review_outputs_are_blinded_and_include_rubric(tmp_path) -> None:
    csv_path = tmp_path / "review.csv"
    key_path = tmp_path / "key.json"
    models = [
        {"model_id": "baseline"},
        {"model_id": "candidate"},
    ]
    common = {
        "case_id": "case-1",
        "category": "routing",
        "repeat": 1,
        "messages": ["Synthetic question"],
        "agent_results": [],
        "source_ids": [],
        "disclaimers": [],
    }
    items = [
        {"model_id": "baseline", "answers": ["First"], **common},
        {"model_id": "candidate", "answers": ["Second"], **common},
    ]

    model_comparison.write_human_review(
        csv_path,
        key_path,
        "comparison",
        models,
        items,
    )

    csv_text = csv_path.read_text(encoding="utf-8")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    assert "output_A" in csv_text
    assert "output_B" in csv_text
    assert set(key["labels"]) == {"A", "B"}
    assert "scale" in key["rubric"]
