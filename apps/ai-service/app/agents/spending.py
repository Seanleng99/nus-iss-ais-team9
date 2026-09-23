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
        
        # Convert Pydantic models to dicts for analysis (ensure JSON-serializable)
        transactions = [
            {
                "category": txn.category,
                "amount": {"currency": txn.amount.currency, "amount": txn.amount.amount},
                "occurred_on": txn.occurred_on.isoformat() if hasattr(txn.occurred_on, 'isoformat') else str(txn.occurred_on),
            }
            for txn in snapshot.historical_transactions or snapshot.recent_transactions
        ]
        
        # Run statistical analysis
        analysis = analyze_spending_patterns(
            transactions=transactions,
            current_month_start=snapshot.period_start,
        )
        
        # Convert analysis results to JSON-serializable format
        safe_analysis = {
            "category_trends": [],
            "temporal_patterns": [],
            "anomalies": [],
            "data_quality": analysis["data_quality"],
            "months_analyzed": analysis["months_analyzed"],
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
    
    def _model_message(
        self,
        task: AgentTask,
        sanitized_message: str,
        grounding: dict,
    ) -> str:
        """Prepare structured input for LLM interpretation with guided responses."""
        
        # Determine data quality context
        data_quality = grounding.get("data_quality", "insufficient")
        months_analyzed = grounding.get("months_analyzed", 0)
        
        quality_context = ""
        if data_quality == "insufficient":
            quality_context = (
                "Note: The user has limited transaction data (less than 1 month). "
                "Focus on encouraging consistent tracking and explain that insights will improve with more data. "
                "Provide general financial education rather than specific pattern analysis."
            )
        elif data_quality == "limited":
            quality_context = (
                f"The user has {months_analyzed} month(s) of data. "
                "Some early patterns may be visible, but emphasize that 3-6 months provides more reliable insights. "
                "Highlight any clear anomalies or strong trends while noting the preliminary nature."
            )
        elif data_quality == "good":
            quality_context = (
                f"The user has {months_analyzed} months of data, providing reliable insights. "
                "You can confidently identify patterns and provide specific recommendations."
            )
        else:  # excellent
            quality_context = (
                f"The user has {months_analyzed}+ months of comprehensive data. "
                "Provide detailed, confident analysis with specific, actionable recommendations."
            )
        
        # Convert grounding to JSON-safe format (handle date objects)
        safe_grounding = {}
        for key, value in grounding.items():
            if isinstance(value, list):
                safe_grounding[key] = []
                for item in value:
                    if isinstance(item, dict):
                        safe_item = {}
                        for k, v in item.items():
                            if hasattr(v, 'isoformat'):
                                safe_item[k] = v.isoformat()
                            else:
                                safe_item[k] = v
                        safe_grounding[key].append(safe_item)
                    else:
                        safe_grounding[key].append(item)
            elif hasattr(value, 'isoformat'):
                safe_grounding[key] = value.isoformat()
            else:
                safe_grounding[key] = value
        
        message_payload = {
            "user_request": sanitized_message,
            "analysis_results": safe_grounding,
            "data_quality_context": quality_context,
            "instruction": (
                "You are a supportive, educational financial coach analyzing spending patterns. "
                "Your response should follow this structure:\n\n"
                
                "1. **ACKNOWLEDGE & VALIDATE**: Start by acknowledging the user's question and validating their interest in understanding their finances. "
                "Make them feel supported, not judged.\n\n"
                
                "2. **KEY FINDINGS**: Present 2-3 most important insights from the data. For each:\n"
                "   - State what the data shows (use specific numbers)\n"
                "   - Explain WHY this matters (financial impact or behavioral insight)\n"
                "   - Note if this is normal, concerning, or positive\n\n"
                
                "3. **CONTEXT & EDUCATION**: Help the user understand their spending in broader context:\n"
                "   - Compare to common benchmarks if relevant (e.g., 'Many people spend 10-15% on dining')\n"
                "   - Explain any financial concepts (e.g., what constitutes a spending anomaly)\n"
                "   - Normalize their experience where appropriate\n\n"
                
                "4. **ACTIONABLE GUIDANCE**: Provide 2-3 specific, achievable suggestions:\n"
                "   - Prioritize by impact (high-impact changes first)\n"
                "   - Make suggestions concrete and measurable\n"
                "   - Include both 'quick wins' and longer-term strategies\n"
                "   - Frame positively (what they CAN do, not restrictions)\n\n"
                
                "5. **NEXT STEPS & ENCOURAGEMENT**: End with:\n"
                "   - One specific action they can take this week\n"
                "   - Encouragement about their financial awareness journey\n"
                "   - 2-3 relevant follow-up questions to help them explore further (see examples below)\n\n"
                
                "FOLLOW-UP QUESTION EXAMPLES (choose 2-3 most relevant to the user's situation):\n"
                "- 'Would you like me to break down your spending by category in more detail?'\n"
                "- 'Should we look at which specific days or weeks had the highest spending?'\n"
                "- 'Would you like to set a budget target for any of these categories?'\n"
                "- 'Do you notice any patterns in your weekend vs weekday spending?'\n"
                "- 'Would you like to compare this month to previous months?'\n"
                "- 'Should we identify your top 3 spending categories to focus on?'\n"
                "- 'Would you like tips on reducing spending in [specific category]?'\n"
                "- 'Are you working toward any specific savings goals I can help with?'\n"
                "- 'Would you like to track progress on any particular spending habit?'\n"
                "- 'Should we review your recurring expenses to see if any can be reduced?'\n\n"
                
                "IMPORTANT GUIDELINES:\n"
                "- Use warm, supportive, non-judgmental language\n"
                "- Avoid assumptions about lifestyle, income, or priorities\n"
                "- Reference actual numbers from the data (amounts, percentages, dates)\n"
                "- Don't preach or lecture—be a helpful coach\n"
                "- If data is limited, be honest about uncertainty while still providing value\n"
                "- Celebrate positive patterns, not just problems\n"
                "- Never shame or criticize spending choices\n\n"
                
                f"{quality_context}\n\n"
                
                "Example response tone: 'I notice your dining spending increased from $95 to $450 this month. "
                "This is 373% higher than your average! While occasional splurges are normal, this could impact your monthly budget. "
                "Many people see spikes around special occasions. Consider setting a fun money category for these moments. "
                "This week, you might review if this was a one-time event or a new pattern. Great job tracking your spending!'"
            ),
        }
        
        return json.dumps(message_payload, ensure_ascii=True)
    
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
