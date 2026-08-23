from app.agents.base import BaseAgent
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    CapabilityName,
    CapabilityResult,
    UserFinancialSnapshot,
)
from app.tools.registry import call_tool


class SpendingAgent(BaseAgent):
    name = AgentName.SPENDING
    prompt_id = "agent_spending"

    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        totals = call_tool(self.name, "transaction_summarizer", snapshot)
        return {
            "category_totals": totals,
            "transaction_count": len(snapshot.recent_transactions),
        }

    def _capabilities(
        self,
        task: AgentTask,
        grounding: dict,
        result: AgentResult,
    ) -> list[CapabilityResult]:
        del result
        return [
            CapabilityResult(
                capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
                provider=self.name.value,
                provider_task_id=task.task_id,
                data={
                    "category_totals": grounding["category_totals"],
                    "transaction_count": grounding["transaction_count"],
                },
                evidence_refs=[f"tool:{task.task_id}:transaction_summarizer"],
            )
        ]
