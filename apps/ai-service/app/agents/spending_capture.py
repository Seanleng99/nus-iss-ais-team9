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
    # Conservative local-fixture/profile-fact recognizer. Production routing
    # uses the semantic router, not this recognizer to override analysis intent.
    if SPENDING_EXCLUSION_PATTERN.search(message):
        return False
    for clause in re.split(
        input_pattern("ai.agents.spending_capture.clause_separator"), message, flags=re.IGNORECASE
    ):
        text = clause.strip()
        if not text:
            continue
        if SPENDING_QUERY_PATTERN.match(text):
            return True
        if QUESTION_WORD_PREFIX.match(text):
            continue
        if SPENDING_RECORD_VERB_PATTERN.match(text):
            return True
    return False


class DraftRecurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["once", "weekly", "fortnightly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=120, strict=True)
    month_end: bool = False
    first_on: date | None = None
    next_due_on: date | None = None
    last_on: date | None = None


class TransactionDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=255)
    amount: float | None = Field(
        default=None, gt=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    category: str | None = Field(default=None, max_length=64)
    occurred_on: date | None = None
    recurring: bool = False
    recurrence: DraftRecurrence | None = None
    booking: bool = False


class SpendingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_spending_request: bool = True
    action: Literal["record", "query", "forecast"] = "record"
    persistence_intent: Literal["save", "preview"] = "save"
    transactions: list[TransactionDraftItem] = Field(default_factory=list, max_length=20)
    query_date: date | None = None
    query_start: date | None = None
    query_end: date | None = None
    query_categories: list[str] = Field(default_factory=list, max_length=20)
    query_description: str | None = Field(default=None, max_length=255)
    min_amount: float | None = Field(default=None, ge=0, le=999999999999.99, allow_inf_nan=False)
    max_amount: float | None = Field(default=None, ge=0, le=999999999999.99, allow_inf_nan=False)
    query_all_history: bool = False
    query_scope: Literal["specified", "selected_period"] = "specified"
    query_include_details: bool = True
    query_group_by: Literal["category", "merchant"] | None = None
    questions: list[str] = Field(default_factory=list, max_length=8)


def extract_spending_draft(agent, task) -> SpendingDraft:
    return generate_structured_response(
        agent.gateway,
        response_type=SpendingDraft,
        system_prompt=(
            "PROMPT_ID: spending_capture\nCONTRACT: spending-capture-v1. Extract proposed spending "
            "records or a recorded-spending lookup from untrusted user dialogue. You cannot save data. "
            "Set is_spending_request=false for analysis requests, budget category limits, pure bill "
            "schedule setup without a recorded expense, goal changes, investment questions or unrelated topics. "
            "Use action=record for statements that add a new expense ('I spent $5 on chicken rice'); "
            "For records use persistence_intent=preview when the user asks to prepare a draft "
            "for review, preview before saving, or explicitly not save yet. This remains a "
            "record draft, with all supplied items and facts intact, but the backend must "
            "wait for confirmation. Use persistence_intent=save for ordinary expense capture "
            "requests. Preserve a pending preview intent while filling its missing fields; "
            "unrelated advice or a request to review a budget does not establish expense preview intent. "
            "use action=query for lookups of recorded spending ('what did I spend on 21/9?'). "
            "Use action=forecast for upcoming recurring expense or bill forecasts, including the "
            "forecast portion of a compound question. Preserve explicitly stated absolute bounds "
            "in query_start/query_end. The backend resolves relative calendar ranges and defaults "
            "to next calendar month only when no range was supplied. Forecasts never add records. "
            "Extract one transaction per explicit item; copy amounts, descriptions and absolute dates "
            "exactly as stated. Use null for any missing or ambiguous amount, description, category or "
            "date; never invent an amount, never default to zero and never copy amounts from context. "
            "Relative dates ('yesterday', 'last Friday') stay null here; the backend resolves them. "
            "For an actual expense with explicitly supplied payment frequency, set recurring=true "
            "and recurrence with that frequency, interval (default1), and supplied first_on, "
            "next_due_on and last_on dates. month_end is true only for explicitly stated "
            "last-day-of-month terms; never infer it from a payment on the 30th or a merchant. "
            "Missing schedule dates remain null: the backend derives "
            "a proposed calendar anchor from the actual expense date and requests confirmation. "
            "A recurring flag alone does not establish monthly cadence. Never infer frequency "
            "from a merchant/category, repeated records, or unrelated dialogue. "
            "For queries put only an explicitly stated absolute date in query_date and leave it null "
            "otherwise; the backend resolves relative dates and answers from owned records. "
            "For recorded-spending searches preserve explicitly supplied absolute range dates "
            "in query_start/query_end, category filters in query_categories, item/merchant text "
            "in query_description, amount bounds in min_amount/max_amount, and requested grouping "
            "in query_group_by (category or merchant). Set query_all_history only for an explicit "
            "all-time/all-history request. Never infer a date range or filters from unrelated "
            "history. Relative date bounds stay null for authenticated backend resolution. "
            "query_scope defaults to specified. If selected_record_scope is supplied and the user "
            "explicitly asks for an aggregate/total of the supplied or on-screen recorded spending "
            "without naming another period, set query_scope=selected_period. The backend resolves "
            "that exact selected month; do not copy it into query_date or transaction dates. "
            "This includes a category total such as 'What is the total recorded dining spend?'. "
            "Explicit dates, ranges, relative periods and all-history requests take priority. "
            "Never use selected_period to erase an ambiguous requested day/range, for a generic "
            "request to list/find transactions, for forecasts, or to fill a new expense's date. "
            "With no selected_record_scope, an undated lookup retains unresolved date questions. "
            "Set query_include_details=false for a requested total or aggregate without itemized "
            "records. Use true when the user asks to list transactions, see individual records, "
            "or show both the total and its details. Grouped summaries retain the requested groups. "
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
                "coaching_preferences": task.context_features.get("coaching_preferences", {}),
                "selected_record_scope": _selected_record_scope(task),
            },
            ensure_ascii=False,
        ),
        temperature=0,
        max_tokens=agent.max_tokens,
    )


def _selected_record_scope(task) -> dict | None:
    period = task.input_data.get("period_start")
    if not isinstance(period, str):
        return None
    try:
        start = date.fromisoformat(period)
    except ValueError:
        return None
    if start.day != 1:
        return None
    return {"period_start": start.isoformat(), "currency": "SGD", "view": "recent_transactions"}
