import json
from pathlib import Path

import pytest
import yaml

from infra.scripts.load_model_role_policy import load_policy

ROOT = Path(__file__).resolve().parents[3]


def test_release_role_policy_matches_local_and_bootstrap_configuration():
    expected = json.loads(load_policy())
    local = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines()
                 if "=" in line and not line.startswith("#"))
    template = yaml.load((ROOT / "infra/aws/demo-application.yaml").read_text(), Loader=yaml.BaseLoader)
    containers = template["Resources"]["AiTaskDefinition"]["Properties"]["ContainerDefinitions"]
    environment = {item["Name"]: item["Value"] for item in containers[0]["Environment"]}
    assert json.loads(local["MODEL_ROLE_OVERRIDES"]) == expected
    assert json.loads(environment["MODEL_ROLE_OVERRIDES"]) == expected
    assert local["MAX_MODEL_TOKENS_PER_RUN"] == environment["MAX_MODEL_TOKENS_PER_RUN"] == "80000"
    assert "PROMPT_SET_VERSION" not in local and "PROMPT_SET_VERSION" not in environment
    assert local["MODEL_REASONING_EFFORT"] == environment["MODEL_REASONING_EFFORT"] == "medium"
    assert local["MODEL_MAX_TOKENS"] == environment["MODEL_MAX_TOKENS"] == "3200"
    assert expected["agent_investment_education"]["max_tokens"] == 4000
    assert expected["goal_input_requirements"] == {"reasoning_effort": "low", "max_tokens": 1000}
    for role in ("agent_budget", "agent_goal_strategy", "agent_spending"):
        assert expected[role] == {"reasoning_effort": "medium", "max_tokens": 3200}


@pytest.mark.parametrize("policy", [{}, {"router": {"max_tokens": 1600}},
    {"router": {"max_tokens": True, "reasoning_effort": "low"}},
    {"router": {"max_tokens": 9000, "reasoning_effort": "low"}},
    {"router": {"max_tokens": 1600, "reasoning_effort": "invalid"}},
])
def test_invalid_role_policy_is_rejected_before_publishing(tmp_path, policy):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        load_policy(path)
