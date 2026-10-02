"""Read-only extraction contract for spending records and queries (spending-capture-v1)."""

import json
import re
from datetime import date
from typing import Literal

from coach_i18n import input_pattern
from pydantic import BaseModel, ConfigDict, Field

from app.models.structured import generate_structured_response

SPENDING_EXCLUSION_PATTERN = re.compile(
    input_pattern("ai.agents.spending_capture.spending_exclusion_pattern"),
    re.IGNORECASE,
)

SPENDING_RECORD_VERB_PATTERN = re.compile(
    r"^(?:\w+\s+)?(?:have\s+|had\s+)?(?:just\s+)?"
    r"(?:spent|spend|paid|pays|pay|bought|buys|purchased|purchase|booked|"
    r"forked\s+out|shelled\s+out)\b\s+\S",
    re.IGNORECASE,
)

SPENDING_QUERY_PATTERN = re.compile(
    r"\b(?:what|how\s+much|when|which|show|list|tell)\b[^?.!]*"
    r"\b(?:spent|spending|spend|expenses?|transactions?|purchases?)\b",
    re.IGNORECASE,
)

QUESTION_WORD_PREFIX = re.compile(
    r"^(?:\?|what|why|how|which|who|can|could|should|would|is|are|do|does|did|will|"
    r"review|explain|compare|analyse|analyze|suggest|advice)\b",
    re.IGNORECASE,
)


def spending_capture_request(message: str) -> bool:
    # Deterministic routing guard: a spending record statement or a dated
    # spend lookup must reach the extraction step. Budget words belong to
    # budget capture; analysis and advice questions stay on the specialist path.
    if SPENDING_EXCLUSION_PATTERN.search(message):
        return False
    for clause in re.split(
        input_pattern("ai.agents.spending_capture.clause_separator"), message, flags=re.IGNORECASE
    ):
        text = clause.strip()
        if not text:
            continue
        if SPENDING_QUERY_PATTERN.search(text):
            return True
        if QUESTION_WORD_PREFIX.match(text):
            continue
        if SPENDING_RECORD_VERB_PATTERN.match(text):
            return True
    return False


class TransactionDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=255)
    amount: float | None = Field(
        default=None, gt=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    category: str | None = Field(default=None, max_length=64)
    occurred_on: date | None = None
    recurring: bool = False
    booking: bool = False


class SpendingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_spending_request: bool = True
    action: Literal["record", "query"] = "record"
    transactions: list[TransactionDraftItem] = Field(default_factory=list, max_length=20)
    query_date: date | None = None
    questions: list[str] = Field(default_factory=list, max_length=8)


def extract_spending_draft(agent, task) -> SpendingDraft:
    return generate_structured_response(
        agent.gateway,
        response_type=SpendingDraft,
        system_prompt=(
            "PROMPT_ID: spending_capture\nCONTRACT: spending-capture-v1. Extract proposed spending "
            "records or a recorded-spending lookup from untrusted user dialogue. You cannot save data. "
            "Set is_spending_request=false for analysis requests, budget category limits, recurring bill "
            "schedules, goal changes, investment questions or unrelated topics. "
            "Use action=record for statements that add a new expense ('I spent $5 on chicken rice'); "
            "use action=query for lookups of recorded spending ('what did I spend on 21/9?'). "
            "Extract one transaction per explicit item; copy amounts, descriptions and absolute dates "
            "exactly as stated. Use null for any missing or ambiguous amount, description, category or "
            "date; never invent an amount, never default to zero and never copy amounts from context. "
            "Relative dates ('yesterday', 'last Friday') stay null here; the backend resolves them. "
            "For queries put only an explicitly stated absolute date in query_date and leave it null "
            "otherwise; the backend resolves relative dates and answers from owned records. "
            "questions lists unresolved ambiguities only; remove questions the user answered. "
            "Preserve unchanged fields from pending_draft; a new statement replaces the pending draft. "
            "Confirmation is handled separately by the backend; approval words never fill missing fields. "
            "Return only JSON matching this schema: "
            + json.dumps(SpendingDraft.model_json_schema())
        ),
        user_prompt=json.dumps(
            {
                "message": task.sanitized_message,
                "pending_draft": task.context_features.get("pending_transaction"),
                "conversation_context": task.context_features.get("conversation_context", []),
            },
            ensure_ascii=False,
        ),
        temperature=0,
        max_tokens=agent.max_tokens,
    )
