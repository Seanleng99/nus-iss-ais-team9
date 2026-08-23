from app.agents.base import BaseAgent
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CapabilityResult,
    UserFinancialSnapshot,
)
from app.tools.registry import call_tool


class BudgetAgent(BaseAgent):
    name = AgentName.BUDGET
    prompt_id = "agent_budget"

    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        return call_tool(self.name, "budget_calculator", snapshot)

    def _capabilities(
        self,
        task: AgentTask,
        grounding: dict,
        result: AgentResult,
    ) -> list[CapabilityResult]:
        del result
        return [
            CapabilityResult(
                capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
                provider=self.name.value,
                provider_task_id=task.task_id,
                data={
                    "currency": "SGD",
                    "disposable_income": grounding["disposable_income"],
                    "estimated_savings_capacity": grounding["savings"],
                    "calculation_method": grounding["method"],
                },
                evidence_refs=[f"tool:{task.task_id}:budget_calculator"],
            )
        ]
