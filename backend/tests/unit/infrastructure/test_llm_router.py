"""Model routing and cost metering.

Cost is the reason this is tested at all. A pricing bug does not fail a request — it
quietly under-reports spend until the invoice arrives, which is exactly the class of
failure that needs a test rather than monitoring.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from coresync.domain.coaching.entities import TaskClass
from coresync.infrastructure.external.llm.router import (
    PRICING,
    ModelRouter,
    estimate_cost_usd,
    pricing_for,
)

router = ModelRouter(
    chat_deployment="gpt-4o",
    mini_deployment="gpt-4o-mini",
    embedding_deployment="text-embedding-3-small",
)


class TestRouting:
    @pytest.mark.parametrize(
        ("task", "expected"),
        [
            (TaskClass.CHAT, "gpt-4o"),
            (TaskClass.REPORT, "gpt-4o"),
            (TaskClass.VISION, "gpt-4o"),
            (TaskClass.CLASSIFICATION, "gpt-4o-mini"),
            (TaskClass.SUMMARISATION, "gpt-4o-mini"),
            (TaskClass.EMBEDDING, "text-embedding-3-small"),
        ],
    )
    def test_each_task_class_routes_to_its_tier(self, task: TaskClass, expected: str) -> None:
        assert router.deployment_for(task) == expected

    def test_the_mechanical_tasks_take_the_cheap_path(self) -> None:
        """The 60/40 split is the largest cost lever after pre-computed context."""
        assert router.is_cheap_path(TaskClass.CLASSIFICATION)
        assert router.is_cheap_path(TaskClass.SUMMARISATION)
        assert not router.is_cheap_path(TaskClass.CHAT)
        assert not router.is_cheap_path(TaskClass.EMBEDDING)


class TestPricingLookup:
    def test_a_known_model_uses_its_own_price(self) -> None:
        assert pricing_for("gpt-4o-mini") is PRICING["gpt-4o-mini"]

    def test_a_deployment_named_after_a_model_resolves_by_prefix(self) -> None:
        assert pricing_for("gpt-4o-mini-2026-01") is PRICING["gpt-4o-mini"]

    def test_an_unknown_model_is_priced_at_the_expensive_tier(self) -> None:
        """Under-reporting cost is how a budget alarm fails to fire."""
        unknown = pricing_for("some-new-model")
        assert unknown.input_per_million == PRICING["gpt-4o"].input_per_million
        assert unknown.output_per_million == PRICING["gpt-4o"].output_per_million


class TestCost:
    def test_a_typical_chat_turn_costs_what_the_table_says(self) -> None:
        # 1000 prompt + 500 completion on gpt-4o: 1000/1e6*2.50 + 500/1e6*10.00
        cost = estimate_cost_usd(model="gpt-4o", prompt_tokens=1000, completion_tokens=500)
        assert cost == Decimal("0.007500")

    def test_the_cheap_tier_is_an_order_of_magnitude_less(self) -> None:
        expensive = estimate_cost_usd(model="gpt-4o", prompt_tokens=1000, completion_tokens=500)
        cheap = estimate_cost_usd(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
        assert cheap * 10 < expensive

    def test_cached_tokens_are_a_subset_of_prompt_tokens_not_an_addition(self) -> None:
        """Double-counting here would inflate the cost of every cached call."""
        # 1000 prompt of which 800 cached: 200 at full rate, 800 at the cached rate.
        cost = estimate_cost_usd(
            model="gpt-4o", prompt_tokens=1000, completion_tokens=0, cached_tokens=800
        )
        expected = (Decimal(200) * Decimal("2.50") + Decimal(800) * Decimal("1.25")) / Decimal(
            1_000_000
        )
        assert cost == expected.quantize(Decimal("0.000001"))

    def test_caching_is_cheaper_than_not_caching(self) -> None:
        uncached = estimate_cost_usd(model="gpt-4o", prompt_tokens=1000, completion_tokens=0)
        cached = estimate_cost_usd(
            model="gpt-4o", prompt_tokens=1000, completion_tokens=0, cached_tokens=1000
        )
        assert cached < uncached

    def test_a_zero_token_call_costs_nothing(self) -> None:
        assert estimate_cost_usd(model="gpt-4o", prompt_tokens=0, completion_tokens=0) == Decimal(
            "0"
        )

    def test_cost_is_quantised_to_the_stored_scale(self) -> None:
        """``ai_usage_logs.cost_usd`` is NUMERIC(10,6); more precision would be lost."""
        cost = estimate_cost_usd(model="gpt-4o-mini", prompt_tokens=7, completion_tokens=3)
        assert cost.as_tuple().exponent == -6

    def test_cached_tokens_exceeding_prompt_tokens_do_not_go_negative(self) -> None:
        """Defensive: a provider reporting oddly must not produce a negative cost."""
        cost = estimate_cost_usd(
            model="gpt-4o", prompt_tokens=100, completion_tokens=0, cached_tokens=500
        )
        assert cost > Decimal("0")
