from dataclasses import asdict
import json
from app.agents.base import BaseAgent
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CapabilityResult,
    UserFinancialSnapshot,
)
from app.core.telemetry import trace_method
from app.tools.spending_analyzer import analyze_spending_patterns


class SpendingAgent(BaseAgent):
    name = AgentName.SPENDING
    prompt_id = "agent_spending"
    dependency_planning_enabled = True

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        
        # Convert Pydantic models to dicts for analysis
        transactions = [
            {
                "category": txn.category,
                "amount": {"currency": txn.amount.currency, "amount": txn.amount.amount},
                "occurred_on": txn.occurred_on,
            }
            for txn in snapshot.historical_transactions or snapshot.recent_transactions
        ]
        
        # Run statistical analysis
        analysis = analyze_spending_patterns(
            transactions=transactions,
            current_month_start=snapshot.period_start,
        )
        
        # Legacy support - compute category totals from recent transactions
        category_totals = self._compute_category_totals(snapshot.recent_transactions)
        
        return {
            # Legacy support
            "category_totals": category_totals,
            "transaction_count": len(snapshot.recent_transactions),
            
            # NEW: Statistical analysis results
            "category_trends": analysis["category_trends"],
            "temporal_patterns": analysis["temporal_patterns"],
            "anomalies": analysis["anomalies"],
            "data_quality": analysis["data_quality"],
            "months_analyzed": analysis["months_analyzed"],
        }
    
    def _model_message(
        self,
        task: AgentTask,
        sanitized_message: str,
        grounding: dict,
    ) -> str:
        """Prepare structured input for LLM interpretation."""
        return json.dumps({
            "user_request": sanitized_message,
            "analysis_results": grounding,
            "instruction": (
                "Analyze the spending data and generate 3-5 key insights. "
                "For each insight: "
                "1) Explain what the data shows, "
                "2) Why it matters to the user, "
                "3) Reference specific numbers from the data. "
                "Avoid lifestyle assumptions - stick to observed patterns."
            ),
        }, ensure_ascii=True)
    
    def _compute_category_totals(self, transactions: list) -> dict:
        """Compute category totals from transactions."""
        totals = {}
        for txn in transactions:
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
                },
                evidence_refs=[f"tool:{task.task_id}:spending_analyzer"],
            )
        ]
