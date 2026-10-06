"""Publish the checked-in role policy, never inherited ECS configuration."""

import argparse
import json
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "apps/ai-service/app/core/model-role-policy.json"


def load_policy(path: Path = POLICY_PATH) -> str:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or not policy:
        raise ValueError("Model role policy must be a nonempty object")
    for role, settings in policy.items():
        if not isinstance(settings, dict) or set(settings) != {"reasoning_effort", "max_tokens"}:
            raise ValueError(f"Invalid policy fields for {role}")
        if settings["reasoning_effort"] not in {"low", "medium"}:
            raise ValueError(f"Invalid reasoning effort for {role}")
        if type(settings["max_tokens"]) is not int or not 1 <= settings["max_tokens"] <= 8192:
            raise ValueError(f"Invalid output limit for {role}")
    return json.dumps(policy, separators=(",", ":"), sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-env", required=True, type=Path)
    args = parser.parse_args()
    policy = load_policy()
    with args.github_env.open("a", encoding="utf-8") as output:
        output.write(f"MODEL_ROLE_OVERRIDES={policy}\n")


if __name__ == "__main__":
    main()
