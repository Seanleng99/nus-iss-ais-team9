from collections.abc import Sequence

from app.agents.base import BaseAgent
from app.agents.education_access import should_request_education_context
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    DependencyRequest,
    DependencyRequestDraft,
    UserFinancialSnapshot,
)
from app.tools.registry import call_tool


class GoalStrategyAgent(BaseAgent):
    name = AgentName.GOAL_STRATEGY
    prompt_id = "agent_goal_strategy"
    dependency_planning_enabled = True

    def _dependency_requests(self, task: AgentTask) -> Sequence[DependencyRequest]:
        goals = task.input_data.get("goals", [])
        if goals and CapabilityName.MONTHLY_SAVINGS_CAPACITY not in task.resolved_dependencies:
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
            goals
            and should_request_education_context(task.sanitized_message)
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
        questions = []
        if not task.input_data.get("goals"):
            questions.append("What goal amount and target date would you like to plan for?")
        elif not task.context_features.get("has_monthly_income"):
            questions.append(
                "What is your monthly income so the goal feasibility can be assessed?"
            )
        return questions

    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        projections = call_tool(self.name, "goal_projection", snapshot)
        capacity = task.resolved_dependencies.get(CapabilityName.MONTHLY_SAVINGS_CAPACITY)
        grounding: dict = {"projections": projections}
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
