"""Unit tests for BudgetPolicy."""

from tempfile import TemporaryDirectory

from ailen.ai.budget import BudgetPolicy
from ailen.infrastructure.sqlite.connection import SQLiteManager
from ailen.infrastructure.sqlite.migrations import MigrationRunner
from ailen.memory.repository import MemoryRepository


def test_budget_policy_unlimited_only_when_limits_are_none() -> None:
    policy = BudgetPolicy(daily_budget_usd=None, monthly_budget_usd=None)
    allowed, reason, summary = policy.is_budget_available()
    assert allowed is True
    assert reason == "BUDGET_AVAILABLE"
    assert summary["daily_spent_usd"] == 0.0


def test_zero_budget_means_no_cloud_spend() -> None:
    policy = BudgetPolicy(daily_budget_usd=0.0, monthly_budget_usd=0.0)
    allowed, reason, _summary = policy.is_budget_available()
    assert allowed is False
    assert reason == "DAILY_BUDGET_EXCEEDED"


def test_budget_policy_circuit_breaker() -> None:
    with TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_budget.db"
        db_mgr = SQLiteManager(db_path)
        MigrationRunner(db_mgr).run_migrations()
        repo = MemoryRepository(db_mgr)

        policy = BudgetPolicy(
            repository=repo,
            daily_budget_usd=1.0,
            monthly_budget_usd=20.0,
        )

        # Initially 0 spend -> allowed
        allowed, reason, summary = policy.is_budget_available()
        assert allowed is True
        assert reason == "BUDGET_AVAILABLE"

        # Log $0.60 spend -> still under daily limit $1.00
        repo.log_ai_usage("openai", "gpt-4o-mini", 1000, 500, 0.60, 250.0)
        allowed, reason, summary = policy.is_budget_available()
        assert allowed is True
        assert summary["daily_spent_usd"] == 0.60

        # Log another $0.50 spend -> total $1.10 >= $1.00 daily limit -> blocked
        repo.log_ai_usage("openai", "gpt-4o-mini", 1000, 500, 0.50, 250.0)
        allowed, reason, summary = policy.is_budget_available()
        assert allowed is False
        assert reason == "DAILY_BUDGET_EXCEEDED"
        assert summary["daily_spent_usd"] == 1.10
