from app.agents.base import BaseAgent
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CapabilityResult,
    DependencyRequest,
    DependencyRequestDraft,
    UserFinancialSnapshot,
)
from app.tools.registry import call_tool


class BudgetAgent(BaseAgent):
    name = AgentName.BUDGET
    prompt_id = "agent_budget"
    dependency_planning_enabled = True

    def _dependency_requests(self, task: AgentTask) -> list[DependencyRequest]:
        return [
            DependencyRequest(
                requester_task_id=task.task_id,
                requester=self.name,
                capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
                reason_code="BUDGET_CONTEXT_REQUIRES_SPENDING_TOTALS",
                required_output_fields=["category_totals", "transaction_count"],
                required=False,
            )
        ] if self._dependency_options(task) else []

    def _dependency_options(self, task: AgentTask) -> list[DependencyRequestDraft]:
        if (
            int(task.context_features.get("recent_transaction_count", 0)) > 0
            and CapabilityName.TRANSACTION_CATEGORY_TOTALS
            not in task.resolved_dependencies
            and not task.dependency_warnings
        ):
            return [
                DependencyRequestDraft(
                    capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
                    reason_code="BUDGET_CONTEXT_REQUIRES_SPENDING_TOTALS",
                    required_output_fields=["category_totals", "transaction_count"],
                    required=False,
                )
            ]
        return []

    def _missing_input_questions(self, task: AgentTask) -> list[str]:
        if not task.context_features.get("has_monthly_income"):
            return ["What is your monthly income before creating this budget?"]
        return []

    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        grounding = call_tool(self.name, "budget_calculator", snapshot)
        spending = task.resolved_dependencies.get(
            CapabilityName.TRANSACTION_CATEGORY_TOTALS
        )
        if spending is not None:
            grounding["spending_context"] = spending.data
        if task.dependency_warnings:
            grounding["dependency_warnings"] = task.dependency_warnings
        return grounding

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
