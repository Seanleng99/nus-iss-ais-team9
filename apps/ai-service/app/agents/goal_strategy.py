from collections.abc import Sequence

from app.agents.base import BaseAgent
from app.agents.education_access import education_topics, should_request_education_context
from app.agents.goal_capture import extract_goal_draft
from app.core.guardrails import inspect_prompt
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CompletedInvocation,
    DependencyRequest,
    DependencyRequestDraft,
    UserFinancialSnapshot,
)
from app.core.session_context import reported_value
from app.core.telemetry import trace_method
from app.tools.registry import call_tool


class GoalStrategyAgent(BaseAgent):
    name = AgentName.GOAL_STRATEGY
    prompt_id = "agent_goal_strategy"
    dependency_planning_enabled = True

    def run_task(self, task):
        if task.context_features.get("goal_capture") and inspect_prompt(task.sanitized_message).allowed:
            draft = extract_goal_draft(self, task)
            if draft.is_goal_request:
                return CompletedInvocation(result=AgentResult(
                    agent=self.name,
                    summary="An unsaved goal change was proposed. The backend must validate it and show a preview for explicit confirmation before making any change.",
                    rationale=["Goal changes require a backend preview and user confirmation."],
                    confidence=1.0, data={"goal_draft": draft.model_dump(mode="json")},
                ), capabilities=[])
        return super().run_task(task)

    @staticmethod
    def _emergency_fund_request(task: AgentTask) -> bool:
        return (
            "emergency_fund" in task.input_data
            or "emergency fund readiness" in education_topics(task.sanitized_message)
        )

    def _dependency_requests(self, task: AgentTask) -> Sequence[DependencyRequest]:
        goals = task.input_data.get("goals", [])
        if (
            goals and not self._emergency_fund_request(task)
            and CapabilityName.MONTHLY_SAVINGS_CAPACITY not in task.resolved_dependencies
        ):
            return (
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
                    reason_code="GOAL_FEASIBILITY_REQUIRES_CAPACITY",
                    required_output_fields=[
                        "estimated_savings_capacity",
                        "calculation_method",
                    ],
                ),
            )
        if (
            (self._emergency_fund_request(task) or should_request_education_context(task.sanitized_message))
            and CapabilityName.EDUCATION_CONTEXT not in task.resolved_dependencies
            and not any(
                CapabilityName.EDUCATION_CONTEXT.value in warning
                for warning in task.dependency_warnings
            )
        ):
            return (
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=CapabilityName.EDUCATION_CONTEXT,
                    reason_code="GOAL_EXPLANATION_REQUIRES_EDUCATION",
                    required_output_fields=[
                        "evidence_status",
                        "contexts",
                        "sources",
                        "corpus_version",
                    ],
                    required=False,
                ),
            )
        return ()

    def _dependency_options(self, task: AgentTask) -> Sequence[DependencyRequestDraft]:
        if self._emergency_fund_request(task):
            return ()
        goals = task.input_data.get("goals", [])
        if goals and CapabilityName.MONTHLY_SAVINGS_CAPACITY not in task.resolved_dependencies:
            return (
                DependencyRequestDraft(
                    capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
                    reason_code="GOAL_FEASIBILITY_REQUIRES_CAPACITY",
                    required_output_fields=[
                        "estimated_savings_capacity",
                        "calculation_method",
                    ],
                    selection_guidance=(
                        "Request this capability when the user asks whether a supplied "
                        "financial goal is feasible, reachable, or affordable."
                    ),
                ),
            )
        return ()

    def _missing_input_questions(self, task: AgentTask) -> Sequence[str]:
        if self._emergency_fund_request(task):
            # Explain the sourced benchmark first, even without a saved goal/income.
            return ()
        questions = []
        if not task.input_data.get("goals"):
            amount = reported_value(task, "goal_target_amount")
            months = reported_value(task, "goal_target_months")
            if amount and months:
                questions.append(
                    f"You told me your goal target is SGD {amount} over {months} months "
                    "(user-reported). It isn't a saved goal yet. Would you like to create "
                    "a goal with a preview for confirmation?"
                )
            elif amount:
                questions.append(f"You told me your goal target is SGD {amount} (user-reported). What duration in months would you like to plan for?")
            elif months:
                questions.append(f"You told me the duration is {months} months (user-reported). What goal amount would you like to plan for?")
            else:
                questions.append("What goal amount and target date would you like to plan for?")
        elif not task.context_features.get("has_monthly_income"):
            income = reported_value(task, "monthly_income")
            questions.append((
                f"You told me your monthly income is SGD {income} (user-reported). "
                "It hasn't been recorded in your profile. Please update your Profile income "
                "before assessing feasibility against saved records."
            ) if income else (
                "What is your monthly income so the goal feasibility can be assessed?"
            ))
        if any(goal.get("target_amount", {}).get("currency", "SGD") != "SGD" or goal.get("current_amount", {}).get("currency", "SGD") != "SGD" for goal in task.input_data.get("goals", [])):
            questions.append("Please provide goal targets and current amounts in SGD before comparing them with SGD budget capacity; no conversion is assumed.")
        return questions

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        projection_snapshot = snapshot
        if self._emergency_fund_request(task):
            projection_snapshot = snapshot.model_copy(update={
                "goals": [goal for goal in snapshot.goals
                          if goal.current_amount.currency == goal.target_amount.currency],
            })
        projections = call_tool(self.name, "goal_projection", projection_snapshot)
        capacity = task.resolved_dependencies.get(CapabilityName.MONTHLY_SAVINGS_CAPACITY)
        grounding: dict = {"projections": projections}
        if self._emergency_fund_request(task):
            grounding["emergency_fund"] = task.input_data.get("emergency_fund") or call_tool(
                self.name, "emergency_fund_summary", snapshot,
            )
        if capacity is not None:
            monthly_capacity = float(capacity.data["estimated_savings_capacity"])
            feasibility = [
                {
                    "name": projection["name"],
                    "monthly_required": projection["monthly_required"],
                    "estimated_savings_capacity": monthly_capacity,
                    "monthly_shortfall": round(
                        max(float(projection["monthly_required"]) - monthly_capacity, 0.0),
                        2,
                    ),
                    "status": (
                        "feasible"
                        if monthly_capacity >= float(projection["monthly_required"])
                        else "shortfall"
                    ),
                }
                for projection in projections
            ]
            total_required = round(sum(float(item["monthly_required"]) for item in projections), 2)
            grounding["combined_feasibility"] = {
                "monthly_required": total_required, "monthly_capacity": monthly_capacity,
                "monthly_shortfall": round(max(total_required - monthly_capacity, 0), 2),
                "status": "feasible" if total_required <= monthly_capacity else "shortfall",
                "scope": "All listed goals funded concurrently; one shared monthly pool, no per-goal money reserved.",
            }
            grounding.update(
                {
                    "monthly_savings_capacity": capacity.data,
                    "feasibility": feasibility,
                }
            )

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
        if "emergency_fund" in grounding:
            return AgentResult(
                agent=self.name,
                summary=(
                    "目前无法从已保存的资料核实应急基金的一般指引，因此不能据此估算目标金额。"
                    "已记录的交易可能不完整。请提供完整的每月支出，以便继续评估目标。"
                    if grounding.get("response_language") == "Chinese" else
                    "I couldn't verify the general emergency-fund guidance from the saved sources, "
                    "so I can't use it to estimate a target yet. Logged transactions may be incomplete. "
                    "Please share your complete monthly expenses to continue assessing the goal."
                ),
                rationale=["Source guidance was unavailable; no unsupported benchmark was supplied."],
                confidence=1.0,
                data=grounding,
            )
        return AgentResult(
            agent=self.name,
            summary=(
                "已完成目标预测计算，但经批准的教育知识库没有足够资料提供所请求的投资解释。"
                if grounding.get("response_language") == "Chinese"
                else (
                    "The deterministic goal projection is available, but the approved "
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
