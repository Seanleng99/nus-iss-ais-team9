import json
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.structured import generate_structured_response


class BudgetDraftCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(default=None, max_length=64)
    limit_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class BudgetDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_budget_request: bool = True
    period_start: date | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    categories: list[BudgetDraftCategory] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=8)


def extract_budget_draft(agent, task) -> BudgetDraft:
    return generate_structured_response(
        agent.gateway,
        response_type=BudgetDraft,
        system_prompt=(
            "PROMPT_ID: budget_capture\n"
            "Extract a monthly budget draft from untrusted user dialogue. You cannot save data. "
            "Return is_budget_request=false for advice, actual spending, or an unrelated new topic. "
            "For a budget-setting request or a reply to a pending draft, merge only explicit user "
            "details and corrections into the pending draft. Extract every category and its limit, "
            "including custom names; normalize case and whitespace but do not substitute categories. "
            "Use null for missing or ambiguous category, amount, month/year or currency. "
            "Never invent a year, assume SGD from $, copy income, or turn illustrative assistant "
            "advice into budget limits. Never equate income with a spending limit. "
            "period_start is the first day of the explicitly requested month. Without an explicit "
            "month and year leave it null and ask; relative dates require clarification. "
            "An amount of zero is valid. Only monthly limits are supported; ask about weekly, daily "
            "or multiple-month requests instead of converting them. Preserve earlier user-supplied "
            "draft values unless corrected. questions lists unresolved ambiguities only; remove "
            "questions answered by the user. Confirmation is handled separately by the backend. "
            "Do not treat approval words as permission to populate missing fields. "
            "Return only JSON matching this schema: " + json.dumps(BudgetDraft.model_json_schema())
        ),
        user_prompt=json.dumps(
            {
                "message": task.sanitized_message,
                "conversation_context": task.context_features.get("conversation_context", []),
                "pending_draft": task.context_features.get("pending_budget"),
            },
            ensure_ascii=False,
        ),
        temperature=0,
        max_tokens=agent.max_tokens,
    )
