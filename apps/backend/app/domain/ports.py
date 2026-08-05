from datetime import date
from typing import Any, Protocol

from app.domain.schemas import FinancialGoal, Transaction, UserFinancialSnapshot


class UserRepository(Protocol):
    """Persistence boundary for financial profiles and snapshots."""

    def get_financial_snapshot(self, user_id: str) -> UserFinancialSnapshot | None: ...


class TransactionRepository(Protocol):
    """Persistence boundary for transaction-management features."""

    def list_for_user(self, user_id: str) -> list[Transaction]: ...


class GoalRepository(Protocol):
    """Persistence boundary for goal-management features."""

    def list_for_user(self, user_id: str) -> list[FinancialGoal]: ...


class BudgetRepository(Protocol):
    """Persistence boundary for monthly category budgets and actual spending."""

    def spending_by_category(self, user_id: str, period_start: date) -> dict[str, float]: ...

    def get(self, user_id: str, period_start: date) -> Any | None: ...
