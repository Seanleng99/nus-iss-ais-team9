"""Private authority for one correction using unchanged financial tool results."""

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256

from app.models.gateway import ModelGatewayError


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def task_fingerprint(task):
    data = task.model_dump(mode="json", exclude={"status", "attempt"})
    data["context_features"].pop("missing_points", None)
    return fingerprint(data)


@dataclass(frozen=True)
class FinancialGroundingSnapshot:
    grounding: dict
    task_hash: str
    grounding_hash: str

    @classmethod
    def capture(cls, task, grounding):
        return cls(deepcopy(grounding), task_fingerprint(task), fingerprint(grounding))

    def for_repair(self, task, original_data=None):
        if (task_fingerprint(task) != self.task_hash or fingerprint(self.grounding) != self.grounding_hash
                or original_data is not None and fingerprint(original_data) != self.grounding_hash):
            raise ModelGatewayError("Financial repair authority changed.",
                                    code="INVALID_FINANCIAL_REPAIR_CONTEXT", component=task.agent.value)
        return deepcopy(self.grounding)
