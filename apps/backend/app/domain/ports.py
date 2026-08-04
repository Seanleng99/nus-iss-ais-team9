from typing import Protocol

from app.domain.schemas import FinancialGoal, Transaction, UserFinancialSnapshot


class UserRepository(Protocol):
    """Persistence boundary for future profile and identity features."""

    def get_financial_snapshot(self, user_id: str) -> UserFinancialSnapshot | None: ...


class TransactionRepository(Protocol):
    """Persistence boundary for future transaction-management features."""

    def list_for_user(self, user_id: str) -> list[Transaction]: ...


class GoalRepository(Protocol):
    """Persistence boundary for future goal-management features."""

    def list_for_user(self, user_id: str) -> list[FinancialGoal]: ...
