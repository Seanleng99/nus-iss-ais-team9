import json
from functools import lru_cache
from pathlib import Path
from typing import Any

POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "policies"
    / "data-lifecycle-policy.json"
)


@lru_cache(maxsize=1)
def get_data_lifecycle_policy() -> dict[str, Any]:
    with POLICY_PATH.open(encoding="utf-8") as policy_file:
        policy = json.load(policy_file)
    if policy.get("schema_version") != 1:
        raise RuntimeError("Unsupported data lifecycle policy schema")
    return policy


DATA_LIFECYCLE_POLICY = get_data_lifecycle_policy()
DATA_LIFECYCLE_POLICY_VERSION = str(DATA_LIFECYCLE_POLICY["policy_version"])
DATA_EXPORT_SCHEMA_VERSION = int(DATA_LIFECYCLE_POLICY["export_schema_version"])
DURABLE_MEMORY_PURPOSE = "durable_agent_memory"
DURABLE_MEMORY_CONSENT_VERSION = str(
    DATA_LIFECYCLE_POLICY["consent"][DURABLE_MEMORY_PURPOSE]["consent_version"]
)
