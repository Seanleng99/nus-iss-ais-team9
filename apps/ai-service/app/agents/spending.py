import calendar
import json
from datetime import date

from coach_math.calendar import financial_today

from app.agents.base import BaseAgent
from app.agents.spending_capture import extract_spending_draft
from app.core.guardrails import inspect_prompt
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CapabilityResult,
    CompletedInvocation,
    UserFinancialSnapshot,
)
from app.core.telemetry import trace_method
from app.tools.spending_analyzer import analyze_spending_patterns


class SpendingAgent(BaseAgent):
    name = AgentName.SPENDING
    prompt_id = "agent_spending"
    dependency_planning_enabled = True

    def run_task(self, task):
        if task.context_features.get("spending_capture") and inspect_prompt(
            task.sanitized_message
        ).allowed:
            draft = extract_spending_draft(self, task)
            if draft.is_spending_request:
                return CompletedInvocation(
                    result=AgentResult(
                        agent=self.name,
                        summary=(
                            "An unsaved spending entry was proposed. The backend validates it and "
                            "shows an exact preview for explicit confirmation before anything is "
                            "saved. A recorded-spending lookup is answered by the backend from the "
                            "user's own records."
                        ),
                        rationale=[
                            "Spending records require a backend preview and explicit user confirmation."
                        ],
                        confidence=1.0,
                        data={"spending_draft": draft.model_dump(mode="json")},
                    ),
                    capabilities=[],
                )
        return super().run_task(task)

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        period_start = (date.fromisoformat(snapshot.period_start) if snapshot.period_start else financial_today()).replace(day=1)
        period_end = period_start.replace(day=calendar.monthrange(period_start.year, period_start.month)[1])
        # Backend snapshots partition the selected month and prior history.
        # Legacy snapshots can also repeat selected-month rows in history:
        # assign those rows to the recent view without deduplicating real expenses.
        prior_history = snapshot.historical_transactions
        if snapshot.recent_transactions or snapshot.transaction_context.get("history_end"):
            prior_history = [txn for txn in prior_history if date.fromisoformat(txn.occurred_on) < period_start]
        records = [*snapshot.recent_transactions, *prior_history]
        
        # Convert Pydantic models to dicts for analysis (ensure JSON-serializable)
        transactions = [
            {
                "category": txn.category,
                "amount": {"currency": txn.amount.currency, "amount": txn.amount.amount},
                "occurred_on": txn.occurred_on.isoformat() if hasattr(txn.occurred_on, 'isoformat') else str(txn.occurred_on),
            }
            for txn in records
            if txn.amount.currency == "SGD" and date.fromisoformat(txn.occurred_on) <= period_end
        ]
        selected_month_transactions = [txn for txn in transactions
                                       if date.fromisoformat(txn["occurred_on"]) >= period_start]
        
        # Run statistical analysis
        analysis = analyze_spending_patterns(
            transactions=transactions,
            current_month_start=period_start,
        )
        
        # Convert analysis results to JSON-serializable format
        safe_analysis = {
            "category_trends": [],
            "temporal_patterns": [],
            "anomalies": [],
            "data_quality": analysis["data_quality"],
            "months_analyzed": analysis["months_analyzed"],
            "transaction_context": snapshot.transaction_context,
            "analysis_period_start": period_start.isoformat(),
            "analysis_period_end": period_end.isoformat(),
            "analysis_coverage": self._record_coverage(transactions),
            "selected_month_coverage": self._record_coverage(selected_month_transactions),
            "temporal_pattern_scope": "selected_month",
            "currency": "SGD",
            "excluded_currencies": sorted({txn.amount.currency for txn in
                [*snapshot.recent_transactions, *snapshot.historical_transactions]
                if txn.amount.currency != "SGD"}),
        }
        
        # Convert date objects to ISO strings in trends
        for trend in analysis.get("category_trends", []):
            safe_trend = {**trend}
            safe_analysis["category_trends"].append(safe_trend)
        
        # Convert date objects in anomalies
        for anomaly in analysis.get("anomalies", []):
            safe_anomaly = {**anomaly}
            if "occurred_on" in safe_anomaly and hasattr(safe_anomaly["occurred_on"], 'isoformat'):
                safe_anomaly["occurred_on"] = safe_anomaly["occurred_on"].isoformat()
            safe_analysis["anomalies"].append(safe_anomaly)
        
        # Convert date objects in temporal patterns
        for pattern in analysis.get("temporal_patterns", []):
            safe_pattern = {**pattern}
            safe_analysis["temporal_patterns"].append(safe_pattern)
        
        # Legacy support - compute category totals from recent transactions
        category_totals = self._compute_category_totals(snapshot.recent_transactions)
        
        return {
            # Legacy support
            "category_totals": category_totals,
            "transaction_count": len(snapshot.recent_transactions),
            
            # NEW: Statistical analysis results (JSON-safe)
            **safe_analysis,
        }
    
    def _model_message(self, task: AgentTask, sanitized_message: str, grounding: dict) -> str:
        """Let the current question determine depth and presentation."""
        return json.dumps({
            "user_request": sanitized_message,
            "analysis_results": grounding,
            "instruction": (
                "Answer the user's current question directly. Match the requested depth and format; "
                "a simple total needs a brief answer, while a comparison can explain the relevant "
                "differences. Use only supplied amounts and dates. Explain missing coverage or small "
                "samples precisely, without restarting the whole coaching workflow. Do not invent "
                "missing transaction dates when analysis_coverage reports dated records. "
                "category_totals and transaction_count describe the supplied recent/selected-month "
                "view; analysis_coverage describes all analyzed SGD records, including prior history. "
                "Use selected_month_coverage for selected-month amounts and analysis_coverage for "
                "historical coverage and weekday/weekend recorded totals. Empty temporal_patterns "
                "means no concentration was detected for the selected month, not that dates are "
                "missing. Recorded weekday/weekend totals do not establish a recurring habit. "
                "Do not invent population benchmarks, normal spending percentages, transaction details or causes. "
                "A temporal concentration describes recorded spending, not proof of a behavioral "
                "pattern. An anomaly with aggregation=category_month_total describes a monthly "
                "category total, not an individual expense or transaction on the month-start date. "
                "Excluded currencies are never summed or converted; disclose exclusions when relevant. "
                "Offer at most one relevant next step when useful; ask a question only if "
                "needed to answer. Saved preferences may tailor wording, never financial evidence. "
                "Spending entries remain unsaved until the backend displays a preview and the user "
                "confirms it. Never claim saving happened without backend confirmation."
            ),
        }, ensure_ascii=False, default=str)

    @staticmethod
    def _record_coverage(transactions: list[dict]) -> dict:
        """Summarize the exact supplied analyzer set without implying completeness."""
        dates = [date.fromisoformat(txn["occurred_on"]) for txn in transactions]
        weekdays = [txn for txn, day in zip(transactions, dates, strict=True) if day.weekday() < 5]
        weekends = [txn for txn, day in zip(transactions, dates, strict=True) if day.weekday() >= 5]
        return {
            "record_count": len(transactions),
            "dated_record_count": len(dates),
            "distinct_recorded_days": len(set(dates)),
            "first_recorded_on": min(dates).isoformat() if dates else None,
            "last_recorded_on": max(dates).isoformat() if dates else None,
            "total_amount": round(sum(txn["amount"]["amount"] for txn in transactions), 2),
            "weekday": {"record_count": len(weekdays),
                        "total_amount": round(sum(txn["amount"]["amount"] for txn in weekdays), 2)},
            "weekend": {"record_count": len(weekends),
                        "total_amount": round(sum(txn["amount"]["amount"] for txn in weekends), 2)},
        }

    def _compute_category_totals(self, transactions: list) -> dict:
        """Compute category totals from transactions."""
        totals = {}
        for txn in transactions:
            if (txn.amount.currency if hasattr(txn, 'amount') else txn["amount"].get("currency", "SGD")) != "SGD":
                continue
            category = txn.category if hasattr(txn, 'category') else txn.get("category", "other")
            amount = txn.amount.amount if hasattr(txn, 'amount') else txn["amount"]["amount"]
            totals[category] = totals.get(category, 0) + amount
        return totals
    
    @trace_method
    def _capabilities(
        self,
        task: AgentTask,
        grounding: dict,
        result: AgentResult,
    ) -> list[CapabilityResult]:
        return [
            CapabilityResult(
                capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
                provider=self.name.value,
                provider_task_id=task.task_id,
                data={
                    "category_totals": grounding["category_totals"],
                    "transaction_count": grounding["transaction_count"],
                    # NEW fields
                    "category_trends": grounding["category_trends"],
                    "temporal_patterns": grounding["temporal_patterns"],
                    "anomalies": grounding["anomalies"],
                    "insights": result.data.get("insights", []),
                    "summary": result.data.get("summary", ""),
                    "data_quality": grounding["data_quality"],
                    "months_analyzed": grounding["months_analyzed"],
                    "analysis_coverage": grounding["analysis_coverage"],
                    "selected_month_coverage": grounding["selected_month_coverage"],
                    "analysis_period_start": grounding["analysis_period_start"],
                    "analysis_period_end": grounding["analysis_period_end"],
                    "temporal_pattern_scope": grounding["temporal_pattern_scope"],
                },
                evidence_refs=[f"tool:{task.task_id}:spending_analyzer"],
            )
        ]
