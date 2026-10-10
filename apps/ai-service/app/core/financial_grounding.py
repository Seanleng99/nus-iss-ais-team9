"""Private authority for one correction using unchanged financial tool results."""

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256

from app.core.telemetry import log_event
from app.models.gateway import ModelGatewayError


def fingerprint(value):
    log_event("VV entering ", "app.core.financial_grounding", "fingerprint")
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def task_fingerprint(task):
    log_event("VV entering ", "app.core.financial_grounding", "task_fingerprint")
    data = task.model_dump(mode="json", exclude={"status", "attempt"})
    data["context_features"].pop("missing_points", None)
    data["context_features"].pop("review_corrections", None)
    data["context_features"].pop("original_summary", None)
    return fingerprint(data)


@dataclass(frozen=True)
class FinancialGroundingSnapshot:
    grounding: dict
    task_hash: str
    grounding_hash: str
    prompt_content_hash: str

    @classmethod
    def capture(cls, task, grounding, *, prompt_content_hash):
        log_event("VV entering ", "app.core.financial_grounding.FinancialGroundingSnapshot", "capture")
        return cls(deepcopy(grounding), task_fingerprint(task), fingerprint(grounding), prompt_content_hash)

    def for_repair(self, task, original_data=None, *, prompt_content_hash):
        log_event("VV entering ", "app.core.financial_grounding.FinancialGroundingSnapshot", "for_repair")
        if (task_fingerprint(task) != self.task_hash or fingerprint(self.grounding) != self.grounding_hash
                or prompt_content_hash != self.prompt_content_hash
                or original_data is not None and fingerprint(original_data) != self.grounding_hash):
            raise ModelGatewayError("Financial repair authority changed.",
                                    code="INVALID_FINANCIAL_REPAIR_CONTEXT", component=task.agent.value)
        return deepcopy(self.grounding)
