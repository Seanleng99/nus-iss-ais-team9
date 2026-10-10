"""Missing facts produce a scoped, localized question before any model calculation."""
import pytest

from app.agents.budget import BudgetAgent
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentTask, NeedsInputInvocation
from app.models.gateway import LocalFixtureModelGateway


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize("has_commitments", [False, True])
def test_missing_income_clarifies_take_home_and_only_unknown_commitments(locale, has_commitments):
    class NoCalculationGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            pytest.fail("Missing required facts must not invoke a calculation or planner")

    task = AgentTask(agent="budget", sanitized_message="Can I afford a monthly saving of SGD 800?",
        input_data={"recurring_expenses": [{"amount": {"currency": "SGD", "amount": 1500}}]
                    if has_commitments else []},
        context_features={"response_locale": locale, "has_monthly_income": False,
                          "task_assignment": {"requires_income": True}})
    result = BudgetAgent(NoCalculationGateway(), PromptCatalog(), 0.1, 800).run_task(task)
    assert isinstance(result, NeedsInputInvocation) and result.missing_fields == ["monthly_income"]
    question = result.questions[0]
    if locale == "en":
        assert "take-home income" in question and "creating" not in question
        assert ("confirmed monthly expenses" in question) is not has_commitments
    else:
        assert "SGD" not in question and not question.isascii()
        assert not any(word in question for word in ("income", "creating", "assessment"))
    assert len(question) > 10
