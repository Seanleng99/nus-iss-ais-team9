"""Explicit low/expected/high income comparisons without assuming forecasts."""
from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator

from app.services.budget_constraints import Money


class IncomeScenarios(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    low: Money
    expected: Money
    high: Money

    @model_validator(mode="after")
    def order(self):
        if self.period_start.day != 1 or not self.low <= self.expected <= self.high:
            raise ValueError("Choose a first-of-month period and ordered low <= expected <= high take-home amounts")
        return self


def compare_income(session, user_id, request):
    from app.infrastructure.repositories import SQLAlchemyBudgetRepository
    from app.services.budget_capture import BudgetDraft
    from app.services.budget_scenarios import compare_draft
    from app.services.budget_timing import assess_timing
    record = SQLAlchemyBudgetRepository(session).get(user_id, request.period_start)
    if not record or record.currency != "SGD" or not record.planning:
        raise ValueError("Save a confirmed SGD budget before comparing income cases")
    draft = BudgetDraft(period_start=request.period_start, currency="SGD",
        planning={k:v for k,v in record.planning.items() if k != "version"},
        categories=[{"category":c.category,"limit_amount":float(c.limit_amount)} for c in record.categories],
        scenarios=[{"name":label,"take_home_income":getattr(request,key)} for key,label in [("low","Low income"),("expected","Expected income"),("high","High income")]])
    result = compare_draft(draft)
    for item in result["results"]:
        candidate = BudgetDraft.model_validate(item["draft"])
        item["cashflow"] = assess_timing(session,user_id,request.period_start,{c.category:c.limit_amount for c in candidate.categories},candidate.planning)
    result["questions"].append("Income cases are your hypothetical take-home amounts, not predicted probabilities. Category limits and savings stay unchanged; confirmation of actual income is required before adopting changes.")
    return result
