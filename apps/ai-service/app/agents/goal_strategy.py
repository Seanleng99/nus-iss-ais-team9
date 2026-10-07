import json
import math
import re
from collections.abc import Sequence

from coach_i18n import translate
from pydantic import BaseModel, ConfigDict, StrictBool

from app.agents.base import BaseAgent
from app.agents.calculation_summary import goal_calculation_summary
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
from app.models.structured import generate_structured_response
from app.tools.registry import call_tool


class GoalInputRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requires_capacity: StrictBool


class GoalStrategyAgent(BaseAgent):
    name = AgentName.GOAL_STRATEGY
    prompt_id = "agent_goal_strategy"
    dependency_planning_enabled = True

    @staticmethod
    def _illustrative_goal(task):
        """Validate a read-only user-supplied calculation apart from saved records."""
        from app.core.schemas import FinancialGoal
        text = task.sanitized_message
        example = bool(re.search(r"\b(?:if|suppose|hypothetical|illustrative|example)\b", text, re.IGNORECASE))
        if task.context_features.get("goal_capture") or re.search(
            r"\b(?:create|record|update|rename|delete)\b|\bsave\s+(?:this|the|my)\s+goal\b",
            text, re.IGNORECASE,
        ):
            return None
        if re.search(
            r"\b(?:afford|feasible|feasibility|realistic|reach|achieve|on track|can I|will I|should I)\b",
            text, re.IGNORECASE,
        ):
            return None
        amount = reported_value(task, "goal_target_amount")
        months = reported_value(task, "goal_target_months")
        if re.search(r"\b(?:USD|EUR|GBP|MYR|AUD|CAD|CHF|JPY|CNY|HKD|NZD|IDR|INR)\b|(?:US|AU|C|HK|NZ)\$|[\u00a3\u20ac]", text, re.IGNORECASE):
            return None
        monetary_pattern = r"(?<![\w+-])(?:SGD\s*|S\$\s*|\$\s*)(\d{1,12}(?:\.\d{1,2})?|[1-9]\d{0,2}(?:,\d{3})+(?:\.\d{1,2})?)(?![\d,]|\.\d|[A-Za-z])"
        legacy_target_pattern = r"\b(?:want|target|save|saving)\s*(?:is|of|for|to)?\s*(\d[\d,]*(?:\.\d{1,2})?)"
        duration_pattern = r"\b(?:in|over|within)\s+(\d{1,3})\s+months?\b"
        marked_amounts = re.findall(monetary_pattern, text, re.IGNORECASE)
        amounts = marked_amounts or re.findall(legacy_target_pattern, text, re.IGNORECASE)
        durations = re.findall(duration_pattern, text, re.IGNORECASE)
        if len(amounts) > 1 or len(durations) > 1:
            return None
        # One marked SGD target and one explicit duration establish only
        # target / months. Further figures could be contributions, balances,
        # another target or returns; do not invent their meaning.
        if not example and (len(marked_amounts) != 1 or len(durations) != 1):
            return None
        residue = re.sub(monetary_pattern if marked_amounts else legacy_target_pattern, "", text, flags=re.IGNORECASE)
        residue = re.sub(duration_pattern, "", residue, flags=re.IGNORECASE)
        if re.search(r"\d", residue):
            return None
        if len(amounts) == 1:
            amount = amounts[0].replace(",", "")
        if len(durations) == 1:
            months = durations[0]
        if not amount or not months:
            return None
        try:
            if not math.isfinite(float(amount)) or not 0 <= float(amount) <= 999999999999.99:
                return None
            return FinancialGoal(name="Illustrative goal (user-reported, unsaved)",
                target_amount={"amount": float(amount)}, target_months=int(months))
        except (ValueError, TypeError):
            return None

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

    def _emergency_fund_request(self, task: AgentTask) -> bool:
        return (
            "emergency_fund" in task.input_data
            or "emergency fund readiness" in (task.context_features.get("education_topics", []))
        )

    def _dependency_requests(self, task: AgentTask) -> Sequence[DependencyRequest]:
        goals = task.input_data.get("goals", [])
        if (
            goals and self._requires_capacity(task)
            and CapabilityName.MONTHLY_SAVINGS_CAPACITY not in task.resolved_dependencies
        ):
            return (
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
                    reason_code="GOAL_FEASIBILITY_REQUIRES_CAPACITY",
                    required_output_fields=[
                        "calculation_method",
                    ],
                ),
            )
        if (
            (self._emergency_fund_request(task) or
             (bool(task.context_features.get("education_topics"))))
            and (self._emergency_fund_request(task) or not task.context_features.get("education_handled_separately"))
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
        if self._illustrative_goal(task):
            return ()
        goals = task.input_data.get("goals", [])
        if goals and self._requires_capacity(task) and CapabilityName.MONTHLY_SAVINGS_CAPACITY not in task.resolved_dependencies:
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

    def _requires_capacity(self, task: AgentTask) -> bool:
        assignment = task.context_features.get("task_assignment") or {}
        if type(assignment.get("requires_capacity")) is bool:
            task._goal_requires_capacity = assignment["requires_capacity"]
        if task.context_features.get("goal_capture") or self._illustrative_goal(task) or self._emergency_fund_request(task):
            return False
        # Archived catalogues retain their original broad saved-goal policy.
        if task._goal_requires_capacity is None:
            decision = generate_structured_response(
                self.gateway, response_type=GoalInputRequirements,
                system_prompt=self.prompts.get("goal_input_requirements"),
                user_prompt=json.dumps({"message": task.sanitized_message,
                    "follow_up": task.context_features.get("follow_up", {})}, ensure_ascii=False),
                temperature=self.temperature, max_tokens=self.max_tokens,
            )
            task._goal_requires_capacity = decision.requires_capacity
        return task._goal_requires_capacity

    def _missing_input_questions(self, task: AgentTask) -> Sequence[str]:
        if self._illustrative_goal(task):
            return ()
        if self._emergency_fund_request(task):
            # Explain the sourced benchmark first, even without a saved goal/income.
            return ()
        questions = []
        if not task.input_data.get("goals"):
            if self._illustrative_goal(task):
                return []
            if not (task.context_features.get("session_context", {}).get("facts")
                    or task.context_features.get("follow_up", {}).get("status") == "resolved"
                    or re.search(r"\b(?:my|our|saved)\b.*\bgoals?\b", task.sanitized_message, re.IGNORECASE)
                    or re.search(r"\b(?:calculate|assess|evaluate|help (?:me )?plan|plan a savings goal|how much|monthly saving|feasible|afford|projection|project my|reach my)\b", task.sanitized_message, re.IGNORECASE)):
                return []
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
        elif self._requires_capacity(task) and not task.context_features.get("has_monthly_income"):
            income = reported_value(task, "monthly_income")
            questions.append((
                f"You told me your monthly income is SGD {income} (user-reported). "
                "It hasn't been recorded in your profile. Please update your Profile income "
                "before assessing feasibility against saved records."
            ) if income else (
                "What is your monthly income so the goal feasibility can be assessed?"
            ))
        if any(goal.get("target_amount", {}).get("currency", "SGD") != "SGD" or goal.get("current_amount", {}).get("currency", "SGD") != "SGD" for goal in task.input_data.get("goals", [])):
            questions.append("Please provide goal targets and current amounts in SGD before goal calculations; no conversion is assumed.")
        return questions

    def _missing_input_fields(self, task):
        if not task.input_data.get("goals"):
            return [field for field in ("goal_target_amount", "goal_target_months")
                    if not reported_value(task, field)]
        return ["monthly_income"] if self._requires_capacity(task) and not task.context_features.get("has_monthly_income") else []

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        illustrative = self._illustrative_goal(task)
        if illustrative:
            snapshot = snapshot.model_copy(update={"goals": [illustrative]})
        projection_snapshot = snapshot
        if self._emergency_fund_request(task):
            projection_snapshot = snapshot.model_copy(update={
                "goals": [goal for goal in snapshot.goals
                          if goal.current_amount.currency == goal.target_amount.currency],
            })
        projections = call_tool(self.name, "goal_projection", projection_snapshot)
        capacity = task.resolved_dependencies.get(CapabilityName.MONTHLY_SAVINGS_CAPACITY) if self._requires_capacity(task) else None
        grounding: dict = {"projections": projections}
        if not illustrative and not self._emergency_fund_request(task) and not self._requires_capacity(task):
            grounding["calculation_scope"] = "saved_goal_arithmetic"
            grounding["goal_progress"] = [
                {"name": goal.name, "target_amount": goal.target_amount.amount,
                 "current_amount": goal.current_amount.amount,
                 "progress_percent": round(goal.current_amount.amount / goal.target_amount.amount * 100, 2)
                    if goal.target_amount.amount else None}
                for goal in snapshot.goals
            ]
        if illustrative:
            grounding["calculation_scope"] = "Illustrative calculation from user-reported inputs; no goal saved and affordability not assessed."
            grounding["calculation_assumptions"] = {
                "currency": "SGD", "starting_amount": 0,
                "investment_returns_assumed": False,
                "method": "Target divided by months, with equal monthly contributions.",
            }
        if self._emergency_fund_request(task):
            grounding["emergency_fund"] = task.input_data.get("emergency_fund") or call_tool(
                self.name, "emergency_fund_summary", snapshot,
            )
        if capacity is not None and capacity.data.get("source") == "unavailable":
            grounding.update({"monthly_savings_capacity": capacity.data,
                "needs_input": True, "questions": [capacity.data["reason"]],
                "calculation_scope": "Goal projection only; the requested budget has no confirmed savings capacity, so affordability is unavailable."})
        elif capacity is not None and capacity.data.get("source") == "period_plans":
            total_required = round(sum(float(item["monthly_required"]) for item in projections), 2)
            period_results = []
            for row in capacity.data["periods"]:
                known = row.get("source") == "confirmed_plan"
                pool = float(row["estimated_savings_capacity"]) if known else None
                period_results.append({"period_start": row["period_start"],
                    "monthly_required": total_required, "monthly_capacity": pool,
                    "monthly_shortfall": round(max(total_required - pool, 0), 2) if known else None,
                    "status": "feasible" if known and pool >= total_required else "shortfall" if known else "unavailable"})
            grounding.update({"monthly_savings_capacity": capacity.data,
                              "period_feasibility": period_results,
                              "calculation_scope": "Each requested month's confirmed pool funds all listed goals concurrently; missing plans are unavailable. No monthly pool is inferred from a period total."})
        elif capacity is not None:
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
                    translate('goal.emergency_fund_evidence_gap', grounding.get('response_language'))
                ),
                rationale=["Source guidance was unavailable; no unsupported benchmark was supplied."],
                confidence=1.0,
                data=grounding,
            )
        return AgentResult(
            agent=self.name,
            summary=(
                goal_calculation_summary(grounding) + "\n\n"
                + translate('goal.education_gap', grounding.get('response_language'))
            ),
            rationale=[
                translate('education.calculations_preserved', grounding.get('response_language'))
            ],
            confidence=1.0,
            data=grounding,
        )
