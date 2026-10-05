import re
from datetime import date

from coach_i18n import translate
from sqlalchemy.orm import Session

from app.api.financial_schemas import BudgetAlert, BudgetAlertCategory
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyUserRepository,
)

APPROACHING_RATIO = 0.8

STATUS_QUERY_PATTERNS = [
    re.compile(r"\bover\s+(?:my\s+|the\s+)?budget\b", re.IGNORECASE),
    re.compile(r"\bgone\s+over\b[^?.]*\bbudget", re.IGNORECASE),
    re.compile(r"\boverspend(?:ing|t)?\b", re.IGNORECASE),
    re.compile(r"\bexceed(?:ing|s|ed)?\b[^?.]*\b(?:budget|income|limit)s?\b", re.IGNORECASE),
    re.compile(r"\bhow\s+am\s+i\s+doing\b[^?.]*\b(?:budget|spending)\b", re.IGNORECASE),
    re.compile(r"\b(?:budget|spending)\b[^?.]*\bon\s+track\b|\bon\s+track\b[^?.]*\b(?:budget|spending)\b", re.IGNORECASE),
    re.compile(r"\bspending\b[^?.]*\b(?:ok|okay|alright|fine|too\s+high|under\s+control)\b", re.IGNORECASE),
    re.compile(r"\b(?:ok|okay|too\s+high|under\s+control)\b[^?.]*\bspending\b", re.IGNORECASE),
]

EXCLUDED_QUERY_PATTERN = re.compile(
    r"\b(?:create|set|update|change|show|review|plan|make|adjust|increase|decrease)\b",
    re.IGNORECASE,
)

MONEY_PATTERN_HINT = re.compile(r"\$\s*\d|\b\d+(?:\.\d{1,2})?\s*(?:dollars|sgd)\b", re.IGNORECASE)


def parse_budget_status_query(message: str) -> bool:
    text = message.strip()
    if re.search(r"\b(?:and|also|then)\b|[;\n]", text, re.IGNORECASE):
        return False
    if re.search(r"\b(?:explain|define|what is|what are|meaning|goal|emergency fund|retirement)\b", text, re.IGNORECASE):
        return False
    if EXCLUDED_QUERY_PATTERN.search(text):
        return False
    if MONEY_PATTERN_HINT.search(text):
        return False
    return any(pattern.search(text) for pattern in STATUS_QUERY_PATTERNS)


def evaluate_budget_alert(
    monthly_income: float,
    category_limits: list[tuple[str, float]],
    spending: dict[str, float],
) -> BudgetAlert | None:
    total_spent = sum(spending.values())
    category_limits = [
        (category, limit) for category, limit in category_limits if limit > 0
    ]
    total_budget_limit = sum(limit for _, limit in category_limits)

    if monthly_income <= 0 and total_budget_limit <= 0:
        return None

    income_usage = total_spent / monthly_income if monthly_income > 0 else None
    budget_usage = total_spent / total_budget_limit if total_budget_limit > 0 else None

    categories_over: list[BudgetAlertCategory] = []
    categories_at_limit: list[BudgetAlertCategory] = []
    for category, limit in category_limits:
        spent = spending.get(category, 0.0)
        item = BudgetAlertCategory(category=category, spent=spent, limit_amount=limit)
        if spent > limit:
            categories_over.append(item)
        elif spent >= APPROACHING_RATIO * limit:
            categories_at_limit.append(item)

    over_income = monthly_income > 0 and total_spent > monthly_income
    over_total_budget = total_budget_limit > 0 and total_spent > total_budget_limit
    over_budget = bool(categories_over) or over_total_budget
    is_over = over_income or over_budget

    approaching = (
        (income_usage is not None and income_usage >= APPROACHING_RATIO)
        or (budget_usage is not None and budget_usage >= APPROACHING_RATIO)
        or bool(categories_at_limit)
    )

    if not is_over and not approaching:
        return None

    return BudgetAlert(
        status="over" if is_over else "approaching",
        income_usage_percent=round(income_usage * 100, 1) if income_usage is not None else None,
        budget_usage_percent=round(budget_usage * 100, 1) if budget_usage is not None else None,
        over_income=over_income,
        over_budget=over_budget,
        categories_over=categories_over,
        categories_at_limit=categories_at_limit,
        amount_over_income=max(total_spent - monthly_income, 0.0) if over_income else 0.0,
        amount_over_budget=(
            max(total_spent - total_budget_limit, 0.0) if over_total_budget else 0.0
        ),
        total_spent=total_spent,
        monthly_income=monthly_income,
        total_budget_limit=total_budget_limit,
    )


def compute_budget_alert(
    session: Session, user_id: str, period_start: date
) -> BudgetAlert | None:
    profile = SQLAlchemyUserRepository(session).get_profile(user_id)
    monthly_income = (
        float(profile.monthly_income) if profile and profile.monthly_income else 0.0
    )
    budget_record = SQLAlchemyBudgetRepository(session).get(user_id, period_start)
    spending = SQLAlchemyBudgetRepository(session).spending_by_category(user_id, period_start)
    category_limits = (
        [(item.category, float(item.limit_amount)) for item in budget_record.categories]
        if budget_record is not None
        else []
    )
    return evaluate_budget_alert(monthly_income, category_limits, spending)


def _money(amount: float) -> str:
    return f"SGD {amount:,.2f}"


def _month_label(period_start: date) -> str:
    return period_start.strftime("%B %Y")


def describe_budget_alert(alert: BudgetAlert, period_start: date) -> str:
    month = _month_label(period_start)
    if alert.status == "over":
        parts = [
            (
                f"Heads up — you are over your limits for {month}. "
                f"You have spent {_money(alert.total_spent)}"
            )
        ]
        if alert.over_income:
            parts.append(
                f" against monthly income of {_money(alert.monthly_income)} "
                f"({_money(alert.amount_over_income)} over)."
            )
        else:
            parts.append(" this month.")
        if alert.over_budget and alert.total_budget_limit > 0:
            parts.append(
                f" Your total budget is {_money(alert.total_budget_limit)}"
            )
            if alert.amount_over_budget > 0:
                parts.append(f" and you are {_money(alert.amount_over_budget)} over it.")
            else:
                parts.append(".")
        if alert.categories_over:
            listed = ", ".join(
                f"{item.category.capitalize()} ({_money(item.spent)} of {_money(item.limit_amount)})"
                for item in alert.categories_over
            )
            parts.append(f" Categories over their limit: {listed}.")
        return "".join(parts)
    parts = [
        (
            f"Warning signs for {month}: you are approaching your limits. "
            f"You have spent {_money(alert.total_spent)}"
        )
    ]
    if alert.income_usage_percent is not None:
        parts.append(f", which uses {alert.income_usage_percent}% of your monthly income.")
    else:
        parts.append(" this month.")
    if alert.budget_usage_percent is not None:
        parts.append(f" Total budget used: {alert.budget_usage_percent}%.")
    if alert.categories_at_limit:
        listed = ", ".join(
            f"{item.category.capitalize()} ({_money(item.spent)} of {_money(item.limit_amount)})"
            for item in alert.categories_at_limit
        )
        parts.append(f" Categories close to their limit: {listed}.")
    return "".join(parts)


def category_overage_note(
    session: Session, user_id: str, period_start: date, category: str, locale="en"
) -> str | None:
    alert = compute_budget_alert(session, user_id, period_start)
    if alert is None:
        return None
    for item in alert.categories_over:
        if item.category == category:
            return " " + translate("coach_action.over_budget", locale,
                category=category.capitalize(), spent=f"{item.spent:.2f}", limit=f"{item.limit_amount:.2f}")
    return None


def build_status_reply(session: Session, user_id: str, period_start: date) -> str:
    alert = compute_budget_alert(session, user_id, period_start)
    month = _month_label(period_start)
    if alert is not None:
        return describe_budget_alert(alert, period_start)
    profile = SQLAlchemyUserRepository(session).get_profile(user_id)
    monthly_income = (
        float(profile.monthly_income) if profile and profile.monthly_income else 0.0
    )
    budget_record = SQLAlchemyBudgetRepository(session).get(user_id, period_start)
    spending = SQLAlchemyBudgetRepository(session).spending_by_category(user_id, period_start)
    total_spent = sum(spending.values())
    if monthly_income <= 0 and budget_record is None:
        return (
            "You haven't set a monthly income or a budget for this month yet, so I can't "
            f"compare your spending to a target. Add your monthly income on the Profile "
            f"page or set a budget on the Budget page, and I'll flag it if you approach or "
            f"exceed your limits. So far you have spent {_money(total_spent)} in {month}."
        )
    parts = [
        f"You're on track for {month}: {_money(total_spent)} spent"
    ]
    if monthly_income > 0:
        parts.append(f" of {_money(monthly_income)} monthly income.")
    else:
        parts.append(" so far.")
    if budget_record is not None:
        total_limit = sum(float(item.limit_amount) for item in budget_record.categories)
        if total_limit > 0:
            used = total_spent / total_limit * 100
            parts.append(f" Budget used: {used:.1f}% of {_money(total_limit)}.")
    return "".join(parts)
