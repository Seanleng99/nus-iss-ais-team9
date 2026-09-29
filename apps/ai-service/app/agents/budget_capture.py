import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.budget_methods import BudgetMethod
from app.models.structured import generate_structured_response


class PlanningInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_home_income: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    income_basis: Literal["take_home", "gross", "unknown"] = "unknown"
    savings_target: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    expenses_confirmed: bool = False
    use_recorded_spending: bool = False
    method: BudgetMethod = Field(default_factory=BudgetMethod)


class BudgetDraftCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(default=None, max_length=64)
    limit_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: Literal["user", "recorded_spending"] = "user"
    reference_period: date | None = None


class BudgetScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
    take_home_income: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    savings_target: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    categories: list[BudgetDraftCategory] = Field(default_factory=list, max_length=50)
    method: BudgetMethod | None = None


class BudgetDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_budget_request: bool = True
    action: Literal["plan", "compare"] = "plan"
    scenarios: list[BudgetScenario] = Field(default_factory=list, max_length=3)
    planning: PlanningInputs | None = None
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
            "Return is_budget_request=false for actual spending or an unrelated new topic. "
            "Requests to build a realistic category budget are planning requests, not general advice. "
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
            "PLANNING CONTRACT budget-planning-v2: When planning_requested=true, or continuing a "
            "pending planning draft, include planning (even when every field is unknown). "
            "Extract income only if explicitly supplied or explicitly adopted from profile context; "
            "income_basis must be take_home only when the user confirms net/take-home income. "
            "Never assume profile income is take-home. Extract the user-chosen monthly savings target "
            "separately; zero requires an explicit choice. Ask for a monthly SGD amount when savings "
            "are given as a percentage. Never infer savings from the 20% baseline. "
            "Do not include savings transfers among expense categories. Ask about debt payments and "
            "irregular costs; do not infer repayment schedules or convert annual/weekly figures. "
            "Set expenses_confirmed=true only if the user explicitly says the proposed plan includes "
            "ALL expenses/commitments. 'Yes' only answers the latest unambiguous question. "
            "Set use_recorded_spending=true only if the user asks to use recorded spending. "
            "Never invent category limits or redistribute a shortfall. Categories contain explicit "
            "user inputs and unchanged pending suggestions; a deterministic tool adds suggestions. "
            "For corrections, update only specified amounts, mark their source=user, and preserve "
            "other draft values. If a user supplies a category without an amount, keep its amount "
            "null so it can be clarified. Never remove a planning object to bypass a funding gap. "
            "METHODS AND SCENARIOS: planning.method is the explicitly chosen method: flexible, "
            "50_30_20, 80_20, zero_based, pay_yourself_first, or custom. Preserve the pending method "
            "unless changed. Never infer a method or classify a category as needs/wants yourself. "
            "For custom, extract explicit needs/wants/savings percentages; ask if missing or not 100%. "
            "Percentage targets are guidance based on FULL take-home income, never income after bills. "
            "Do not replace savings_target with a percentage-derived amount; ask the user to choose "
            "their monthly savings amount. For zero_based every dollar must be allocated explicitly. "
            "For what-if or comparison requests set action=compare and capture up to three named "
            "scenarios. Each scenario contains ONLY requested overrides to take_home_income, "
            "savings_target, category limits or method. Keep the base draft unchanged. Use short "
            "distinct alphanumeric scenario names. Missing overrides inherit the base; explicit zero "
            "does not mean missing. Hypothetical income must be described as monthly take-home; ask "
            "if its basis is unclear. Use action=compare while continuing a comparison. "
            "Never adopt a scenario implicitly, even if it seems better. Tell the user to reply "
            "'use scenario NAME'; the backend alone adopts a stored scenario. When a pending draft "
            "has action=plan after adoption, do not reuse earlier hypothetical amounts as confirmed "
            "actual income. Require the user's explicit income-basis and coverage confirmation. "
            "Return only JSON matching this schema: " + json.dumps(BudgetDraft.model_json_schema())
        ),
        user_prompt=json.dumps(
            {
                "message": task.sanitized_message,
                "conversation_context": task.context_features.get("conversation_context", []),
                "pending_draft": task.context_features.get("pending_budget"),
                "planning_requested": task.context_features.get("budget_planning", False),
                "recorded_context": task.input_data.get("planning_context", {}),
            },
            ensure_ascii=False,
        ),
        temperature=0,
        max_tokens=agent.max_tokens,
    )
