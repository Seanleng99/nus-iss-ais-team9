from app.agents.base import BaseAgent
from app.agents.education_access import should_request_education_context
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
        message = task.sanitized_message.casefold()
        requests: list[DependencyRequest] = []
        explicit_spending_context = any(
            term in message
            for term in (
                "spending",
                "transaction",
                "expense pattern",
                "expense history",
                "recent purchases",
            )
        )
        if (
            explicit_spending_context
            and int(task.context_features.get("recent_transaction_count", 0)) > 0
            and CapabilityName.TRANSACTION_CATEGORY_TOTALS
            not in task.resolved_dependencies
            and not task.dependency_warnings
        ):
            requests.append(
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
                    reason_code="BUDGET_CONTEXT_REQUIRES_SPENDING_TOTALS",
                    required_output_fields=["category_totals", "transaction_count"],
                    required=False,
                )
            )
        if (
            should_request_education_context(task.sanitized_message)
            and CapabilityName.EDUCATION_CONTEXT not in task.resolved_dependencies
            and not any(
                CapabilityName.EDUCATION_CONTEXT.value in warning
                for warning in task.dependency_warnings
            )
        ):
            requests.append(
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=CapabilityName.EDUCATION_CONTEXT,
                    reason_code="BUDGET_EXPLANATION_REQUIRES_EDUCATION",
                    required_output_fields=[
                        "evidence_status",
                        "contexts",
                        "sources",
                        "corpus_version",
                    ],
                    required=False,
                )
            )
        return requests

    def _dependency_options(self, task: AgentTask) -> list[DependencyRequestDraft]:
        options: list[DependencyRequestDraft] = []
        if (
            int(task.context_features.get("recent_transaction_count", 0)) > 0
            and CapabilityName.TRANSACTION_CATEGORY_TOTALS
            not in task.resolved_dependencies
            and not task.dependency_warnings
        ):
            options.append(
                DependencyRequestDraft(
                    capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
                    reason_code="BUDGET_CONTEXT_REQUIRES_SPENDING_TOTALS",
                    required_output_fields=["category_totals", "transaction_count"],
                    required=False,
                    selection_guidance=(
                        "Request this capability when the user explicitly asks to use "
                        "recent spending, transactions, or expense patterns in the budget."
                    ),
                )
            )
        return options

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
        education = task.resolved_dependencies.get(CapabilityName.EDUCATION_CONTEXT)
        if education is not None:
            grounding.update(education.data)
            grounding["retrieval_consumer"] = self.name.value
        elif any(
            CapabilityName.EDUCATION_CONTEXT.value in warning
            for warning in task.dependency_warnings
        ):
            grounding.update(
                {
                    "evidence_status": "insufficient",
                    "contexts": [],
                    "sources": [],
                    "retrieval_consumer": self.name.value,
                }
            )
        if task.dependency_warnings:
            grounding["dependency_warnings"] = task.dependency_warnings
        return grounding

    def _evidence_gap_result(self, grounding: dict) -> AgentResult:
        return AgentResult(
            agent=self.name,
            summary=(
                "已完成预算计算，但经批准的教育知识库没有足够资料提供所请求的投资解释。"
                if grounding.get("response_language") == "Chinese"
                else (
                    "The deterministic budget calculation is available, but the approved "
                    "Education knowledge base does not contain enough information for the "
                    "requested investment explanation."
                )
            ),
            rationale=[
                "已保留计算结果，未提供缺乏资料支持的教育性内容。"
                if grounding.get("response_language") == "Chinese"
                else (
                    "Calculated values were preserved while unsupported educational "
                    "claims were withheld."
                )
            ],
            confidence=1.0,
            data=grounding,
        )

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
