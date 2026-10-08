"""Internal grounding authority for one correction of the same education task."""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256

from app.core.schemas import AgentName, AgentTask
from app.models.gateway import ModelGatewayError

_AUTHORITY_FIELDS = (
    "contexts", "sources", "corpus_version", "scope", "query_topics", "fallback_topics",
    "excluded_topics", "ordered_topics", "coverage_source_ids", "subquestions",
    "subquestion_coverage", "coverage_assessment", "sourced_evidence_status",
    "source_unanswered_topics", "retrieval_strategy", "semantic_failure_code",
    "security_findings", "source_verification", "response_language", "question_intent",
    "table_requested",
)


def _fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def _task_fingerprint(task: AgentTask) -> str:
    data = task.model_dump(mode="json", exclude={"status", "attempt"})
    # The sole permitted context addition is independently reviewed correction
    # feedback. Request, task, dependencies, language and subject remain fixed.
    data["context_features"].pop("missing_points", None)
    data["context_features"].pop("review_corrections", None)
    data["context_features"].pop("original_summary", None)
    return _fingerprint(data)


def _authority_fingerprint(grounding: dict) -> str:
    return _fingerprint({key: grounding.get(key) for key in _AUTHORITY_FIELDS})


@dataclass(frozen=True)
class EducationGroundingSnapshot:
    """Created only after server grounding; never accepted from model/user JSON."""

    grounding: dict = field(repr=False)
    task_fingerprint: str
    grounding_fingerprint: str
    authority_fingerprint: str
    sanitized_message_fingerprint: str
    prompt_version: str
    prompt_content_hash: str
    expected_corpus_version: str | None

    @classmethod
    def capture(cls, task: AgentTask, grounding: dict, *, sanitized_message: str, prompt_version: str, prompt_content_hash: str, expected_corpus_version: str | None):
        snapshot = deepcopy(grounding)
        return cls(
            grounding=snapshot, task_fingerprint=_task_fingerprint(task),
            grounding_fingerprint=_fingerprint(snapshot),
            authority_fingerprint=_authority_fingerprint(snapshot),
            sanitized_message_fingerprint=sha256(sanitized_message.encode("utf-8")).hexdigest(),
            prompt_version=prompt_version, prompt_content_hash=prompt_content_hash,
            expected_corpus_version=expected_corpus_version,
        )

    def _validate(self, task: AgentTask) -> None:
        if (
            task.agent != AgentName.INVESTMENT_EDUCATION
            or _task_fingerprint(task) != self.task_fingerprint
            or _fingerprint(self.grounding) != self.grounding_fingerprint
        ):
            raise ModelGatewayError(
                "The education repair no longer matches its original validated task and grounding.",
                code="INVALID_EDUCATION_REPAIR_CONTEXT", component="investment_education",
            )

    def authorize_result(self, task: AgentTask, original_data: dict) -> None:
        self._validate(task)
        if _authority_fingerprint(original_data) != self.authority_fingerprint:
            raise ModelGatewayError(
                "The education repair source, corpus or scope authority changed after grounding.",
                code="INVALID_EDUCATION_REPAIR_CONTEXT", component="investment_education",
            )

    def for_repair(self, task: AgentTask, *, sanitized_message: str, prompt_version: str, prompt_content_hash: str, expected_corpus_version: str | None) -> dict:
        self._validate(task)
        if (
            prompt_version != self.prompt_version
            or prompt_content_hash != self.prompt_content_hash
            or expected_corpus_version != self.expected_corpus_version
            or sha256(sanitized_message.encode("utf-8")).hexdigest() != self.sanitized_message_fingerprint
        ):
            raise ModelGatewayError(
                "The education repair question, prompt or corpus no longer matches the original assessment.",
                code="INVALID_EDUCATION_REPAIR_CONTEXT", component="investment_education",
            )
        # Writer selection, model sections and evidence-status updates must
        # never mutate the original quotations or their support decisions.
        return deepcopy(self.grounding)
