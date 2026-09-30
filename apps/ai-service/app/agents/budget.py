from app.agents.base import BaseAgent
from app.agents.budget_capture import PlanningInputs, extract_budget_draft
from app.agents.education_access import should_request_education_context
from app.core.guardrails import inspect_prompt
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CapabilityResult,
    CompletedInvocation,
    DependencyRequest,
    DependencyRequestDraft,
    UserFinancialSnapshot,
)
from app.core.telemetry import trace_method
from app.tools.budget_planner import describe_plan, propose_budget
from app.tools.registry import call_tool


class BudgetAgent(BaseAgent):
    name = AgentName.BUDGET
    prompt_id = "agent_budget"
    dependency_planning_enabled = True

    def run_task(self, task: AgentTask):
        if task.context_features.get("budget_capture") and inspect_prompt(task.sanitized_message).allowed:
            draft = extract_budget_draft(self, task)
            if draft.is_budget_request:
                analysis = None
                if draft.action not in {"review", "alternatives", "continuity", "workspace"} and (task.context_features.get("budget_planning") or draft.planning is not None):
                    if draft.planning is None:
                        draft.planning = PlanningInputs.model_validate(
                            (task.context_features.get("pending_budget") or {}).get("planning") or {}
                        )
                    analysis = propose_budget(
                        draft, task.input_data.get("planning_context", {}),
                        task.context_features.get("pending_budget"),
                    )
                return CompletedInvocation(
                    result=AgentResult(
                        agent=self.name,
                        summary="An unsaved planning settings draft was extracted. The backend will validate owned records, ask for missing details and present an exact preview for separate confirmation. No changes have been saved." if draft.action in {"workspace", "continuity"} else "A read-only comparison of monthly expense limits and savings was requested. The backend will use the user's confirmed commitments or ask them to set those commitments first. No category amounts, goal contributions or debt payments have been inferred, calculated or saved by this extraction step." if draft.action == "alternatives" else "A read-only budget review was requested; the backend will verify the period and compute results from owned records." if draft.action == "review" else describe_plan(draft, analysis) if analysis is not None else (
                            "Budget details have been captured as an unsaved draft. "
                            "Missing details must be supplied and the exact changes confirmed "
                            "before the backend can save them."
                        ),
                        rationale=["Only explicit user-provided limits are eligible for confirmation."],
                        confidence=1.0,
                        data={
                            "budget_draft": draft.model_dump(mode="json"),
                            **({"planning_analysis": analysis} if analysis is not None else {}),
                        },
                    ),
                    capabilities=self._capabilities(task, self._capacity_grounding(task), None) if task.context_features.get("has_monthly_income") else [],
                )
        return super().run_task(task)

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
        if task.input_data.get("saved_budget_capacity", {}).get("source") != "confirmed_plan" and (
            (task.input_data.get("monthly_income") or {}).get("currency", "SGD") != "SGD" or any(item.get("amount", {}).get("currency", "SGD") != "SGD" for item in task.input_data.get("recurring_expenses", []))
        ):
            return ["Please provide income and recurring expenses in SGD before calculating savings capacity; no currency conversion is assumed."]
        if not task.context_features.get("has_monthly_income"):
            return ["What is your monthly income before creating this budget?"]
        return []

    def _capacity_grounding(self, task):
        saved = task.input_data.get("saved_budget_capacity", {})
        if saved.get("source") == "confirmed_plan":
            return {"capacity": saved, "income": saved["take_home_income"],
                    "planned_expenses": saved["planned_expenses"], "savings": saved["estimated_savings_capacity"],
                    "unallocated_income": saved["unallocated_income"], "method": saved["calculation_method"],
                    "capacity_source": "confirmed_plan"}
        baseline = call_tool(self.name, "budget_calculator", UserFinancialSnapshot.model_validate(task.input_data))
        baseline["capacity_source"] = "illustrative_fallback"
        baseline["capacity"] = {"source": "illustrative_fallback", "currency": "SGD",
                                "period_start": saved.get("period_start"), "fallback_reason": saved.get("reason", "No confirmed plan supplied."),
                                "estimated_savings_capacity": baseline["savings"], "disposable_income": baseline["disposable_income"],
                                "calculation_method": baseline["method"],
                                "caveat": "Illustrative estimate from profile income and recorded recurring expenses; income basis and expense coverage are unconfirmed. Not a saved plan or observed savings."}
        return baseline

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        grounding = self._capacity_grounding(task)
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
                data=grounding["capacity"],
                evidence_refs=[f"saved-budget:{grounding['capacity']['period_start']}" if grounding["capacity_source"] == "confirmed_plan" else f"tool:{task.task_id}:budget_calculator"],
            )
        ]
