from collections.abc import Sequence

from app.agents.base import BaseAgent
from app.core.schemas import (
    AgentName,
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
        if capacity is None:
            return {"projections": projections}

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
        return {
            "projections": projections,
            "monthly_savings_capacity": capacity.data,
            "feasibility": feasibility,
        }
