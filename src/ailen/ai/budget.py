"""Economic budget enforcement policy for cloud AI providers.

Tracks daily and monthly spend against configured limits and acts as a circuit breaker
to prevent unexpected cloud charges.
"""

from datetime import UTC, datetime
from typing import Any

from ailen.memory.repository import MemoryRepository


class BudgetPolicy:
    """Evaluates whether cloud AI inference is within budget limits."""

    def __init__(
        self,
        repository: MemoryRepository | None = None,
        daily_budget_usd: float | None = None,
        monthly_budget_usd: float | None = None,
    ) -> None:
        self.repository = repository
        self.daily_budget_usd = daily_budget_usd
        self.monthly_budget_usd = monthly_budget_usd

    def get_spending_summary(self) -> dict[str, Any]:
        """Query and return current spending totals."""
        if not self.repository:
            return {
                "daily_spent_usd": 0.0,
                "monthly_spent_usd": 0.0,
                "daily_limit_usd": self.daily_budget_usd,
                "monthly_limit_usd": self.monthly_budget_usd,
            }

        now = datetime.now(UTC)
        start_of_day = now.strftime("%Y-%m-%dT00:00:00Z")
        start_of_month = now.strftime("%Y-%m-01T00:00:00Z")

        _, _, daily_cost = self.repository.get_ai_usage_totals(since_iso=start_of_day)
        _, _, monthly_cost = self.repository.get_ai_usage_totals(since_iso=start_of_month)

        return {
            "daily_spent_usd": round(daily_cost, 6),
            "monthly_spent_usd": round(monthly_cost, 6),
            "daily_limit_usd": self.daily_budget_usd,
            "monthly_limit_usd": self.monthly_budget_usd,
        }

    def is_budget_available(self) -> tuple[bool, str, dict[str, Any]]:
        """Check if cloud inference is currently allowed by budget.
        
        Returns:
            (is_allowed, reason_code, spending_summary)
        """
        summary = self.get_spending_summary()
        daily_spent = summary["daily_spent_usd"]
        monthly_spent = summary["monthly_spent_usd"]

        # Zero is a hard no-spend limit. Only None means unlimited.
        if self.daily_budget_usd is not None and daily_spent >= self.daily_budget_usd:
            return False, "DAILY_BUDGET_EXCEEDED", summary

        if self.monthly_budget_usd is not None and monthly_spent >= self.monthly_budget_usd:
            return False, "MONTHLY_BUDGET_EXCEEDED", summary

        return True, "BUDGET_AVAILABLE", summary
