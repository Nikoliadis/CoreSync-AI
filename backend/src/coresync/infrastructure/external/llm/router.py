"""Model routing and cost estimation.

Routing by task class is the single largest cost lever after pre-computed context: the
cheap model handles classification and summarisation — roughly 60% of calls — and the
expensive one only answers the user directly (docs/10 §9).

Pricing lives here as data rather than being fetched, because a cost figure that silently
changes under you is worse than one that is occasionally stale: this table is versioned,
reviewable in a diff, and wrong in a way that shows up in a test.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from coresync.domain.coaching.entities import TaskClass

# Cost per 1M tokens in USD, as published 2026-07. Cached input tokens bill at a
# discount, which materially changes the economics of a long system prompt.
_CENT = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class ModelPricing:
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal


PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(Decimal("2.50"), Decimal("10.00"), Decimal("1.25")),
    "gpt-4o-mini": ModelPricing(Decimal("0.15"), Decimal("0.60"), Decimal("0.075")),
    "text-embedding-3-small": ModelPricing(Decimal("0.02"), Decimal("0"), Decimal("0.02")),
}

# An unknown deployment is priced at the most expensive known model rather than zero.
# Under-reporting cost is how a budget alarm fails to fire; over-reporting is merely
# conservative.
_FALLBACK_PRICING = ModelPricing(Decimal("2.50"), Decimal("10.00"), Decimal("1.25"))

# Which tier answers which kind of call. Chat and reports face the user directly and get
# the capable model; everything else is a mechanical transformation the cheap one does
# just as well.
_EXPENSIVE_TASKS = frozenset({TaskClass.CHAT, TaskClass.REPORT, TaskClass.VISION})


@dataclass(frozen=True, slots=True)
class ModelRouter:
    """Maps a task class to a deployment name.

    Deployment names, not model names: on Azure you address the deployment, and the two
    are only equal by convention.
    """

    chat_deployment: str
    mini_deployment: str
    embedding_deployment: str

    def deployment_for(self, task_class: TaskClass) -> str:
        if task_class is TaskClass.EMBEDDING:
            return self.embedding_deployment
        if task_class in _EXPENSIVE_TASKS:
            return self.chat_deployment
        return self.mini_deployment

    def is_cheap_path(self, task_class: TaskClass) -> bool:
        return task_class not in _EXPENSIVE_TASKS and task_class is not TaskClass.EMBEDDING


def pricing_for(model: str) -> ModelPricing:
    """Pricing for a model or deployment name.

    Deployments are conventionally named after the model they serve, so an exact match is
    tried first and then a prefix match, before falling back to the expensive tier.

    Prefixes are tested longest-first, because ``gpt-4o`` is a prefix of ``gpt-4o-mini``:
    shortest-first would bill every dated mini deployment at the full gpt-4o rate.
    """
    if model in PRICING:
        return PRICING[model]
    for known in sorted(PRICING, key=len, reverse=True):
        if model.startswith(known):
            return PRICING[known]
    return _FALLBACK_PRICING


def estimate_cost_usd(
    *, model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0
) -> Decimal:
    """Cost of one call, quantised to the storage scale of ``ai_usage_logs.cost_usd``.

    ``cached_tokens`` is a subset of ``prompt_tokens``, not an addition to it — the
    provider reports it that way, and double-counting would inflate every cached call.
    """
    pricing = pricing_for(model)
    billable_prompt = max(0, prompt_tokens - cached_tokens)
    million = Decimal(1_000_000)

    total = (
        Decimal(billable_prompt) * pricing.input_per_million
        + Decimal(cached_tokens) * pricing.cached_input_per_million
        + Decimal(completion_tokens) * pricing.output_per_million
    ) / million
    return total.quantize(_CENT, rounding=ROUND_HALF_UP)
