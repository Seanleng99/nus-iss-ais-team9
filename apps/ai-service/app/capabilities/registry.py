from collections.abc import Iterable

from app.core.schemas import (
    AgentName,
    CapabilityDefinition,
    CapabilityName,
    CapabilityProviderType,
)


class CapabilityRegistryError(ValueError):
    """Raised when a dependency capability is unknown or unauthorized."""


DEFAULT_CAPABILITIES = (
    CapabilityDefinition(
        capability=CapabilityName.TRANSACTION_CATEGORY_TOTALS,
        provider="transaction_summarizer",
        provider_type=CapabilityProviderType.TOOL,
        allowed_requesters={AgentName.SPENDING},
        required_inputs=["recent_transactions"],
    ),
    CapabilityDefinition(
        capability=CapabilityName.MONTHLY_BUDGET_BASELINE,
        provider="budget_calculator",
        provider_type=CapabilityProviderType.TOOL,
        allowed_requesters={AgentName.BUDGET},
        required_inputs=["monthly_income", "recurring_expenses"],
    ),
    CapabilityDefinition(
        capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
        provider=AgentName.BUDGET.value,
        provider_type=CapabilityProviderType.AGENT,
        allowed_requesters={AgentName.GOAL_STRATEGY},
        required_inputs=["monthly_income", "recurring_expenses"],
    ),
    CapabilityDefinition(
        capability=CapabilityName.GOAL_PROJECTION,
        provider="goal_projection",
        provider_type=CapabilityProviderType.TOOL,
        allowed_requesters={AgentName.GOAL_STRATEGY},
        required_inputs=["goals"],
    ),
    CapabilityDefinition(
        capability=CapabilityName.INVESTMENT_EDUCATION_EVIDENCE,
        provider=AgentName.INVESTMENT_EDUCATION.value,
        provider_type=CapabilityProviderType.AGENT,
        allowed_requesters={AgentName.RISK_COMPLIANCE},
        required_inputs=["sanitized_message"],
    ),
    CapabilityDefinition(
        capability=CapabilityName.POLICY_CONTEXT,
        provider="trusted_retriever",
        provider_type=CapabilityProviderType.TOOL,
        allowed_requesters={AgentName.RISK_COMPLIANCE},
        required_inputs=["sanitized_message"],
    ),
)


class CapabilityRegistry:
    def __init__(self, definitions: Iterable[CapabilityDefinition] | None = None) -> None:
        items = tuple(definitions) if definitions is not None else DEFAULT_CAPABILITIES
        self._definitions = {item.capability: item for item in items}
        if len(self._definitions) != len(items):
            raise CapabilityRegistryError("Capability names must be unique.")

    def authorize(
        self,
        requester: AgentName,
        capability: CapabilityName,
    ) -> CapabilityDefinition:
        try:
            definition = self._definitions[capability]
        except KeyError as exc:
            raise CapabilityRegistryError(f"Unknown capability: {capability}") from exc
        if requester not in definition.allowed_requesters:
            raise CapabilityRegistryError(
                f"{requester.value} cannot request capability {capability.value}"
            )
        return definition

    def get(self, capability: CapabilityName) -> CapabilityDefinition:
        try:
            return self._definitions[capability]
        except KeyError as exc:
            raise CapabilityRegistryError(f"Unknown capability: {capability}") from exc
