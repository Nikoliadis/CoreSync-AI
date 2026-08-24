"""Search latency against a realistic catalogue.

docs/15 sets the Phase 3 exit criterion at **p95 under 150 ms** for food search. That
number is not decoration: search is on the path of every single log, and a diary that
takes a beat to answer is one people stop opening.

Measured against a catalogue seeded to a realistic size rather than the handful of rows a
functional test needs — an index that looks fine over 57 rows tells you nothing. What is
being timed is the query, not the HTTP stack, because the query is the part that degrades
with catalogue size and the part an index change can fix.

Marked `slow`: it seeds thousands of rows. It is a gate, not something to run on every
save.
"""

from __future__ import annotations

import statistics
import time
from decimal import Decimal
from uuid import uuid5

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coresync.core.ids import uuid7
from coresync.infrastructure.database.repositories.nutrition import SqlAlchemyFoodRepository
from coresync.infrastructure.seed.off_import import OFF_NAMESPACE

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# The budget from docs/15, and the size the catalogue is expected to reach once the
# Open Food Facts import has run for Greece (~12k products, ~86% usable).
P95_BUDGET_MS = 150.0
CATALOGUE_SIZE = 10_000
ITERATIONS = 60

# Real Greek search terms, chosen to exercise the paths that behave differently:
# a common prefix, an accented word typed without accents, a Latin brand, a typo.
QUERIES = [
    "γάλα",
    "γαλα",
    "ΓΑΛΑ",
    "γιαουρτι",
    "ψωμι ολικης",
    "nutella",
    "κοτοπουλο",
    "τυρι",
    "μπανανα",
    "ζυμαρικ",
]

# Word stems that combine into plausible product names, so the index sees realistic
# term distribution rather than ten thousand variations of one string.
_HEADS = ["Γάλα", "Γιαούρτι", "Ψωμί", "Τυρί", "Χυμός", "Μπάρα", "Ζυμαρικά", "Κοτόπουλο"]
_TAILS = ["πλήρες", "ολικής", "light", "classic", "bio", "family", "χωριάτικο", "παραδοσιακό"]
_BRANDS = ["ΔΕΛΤΑ", "ΓΙΩΤΗΣ", "Nutella", "Barilla", "Misko", "Κρι Κρι", "Olympos"]


@pytest_asyncio.fixture(scope="module")
async def loaded_catalogue(postgres_url: str) -> str:
    """Insert a realistic catalogue once for the whole module."""
    engine = create_async_engine(postgres_url)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)

    async with factory() as session:
        rows = []
        for index in range(CATALOGUE_SIZE):
            head = _HEADS[index % len(_HEADS)]
            tail = _TAILS[(index // len(_HEADS)) % len(_TAILS)]
            brand = _BRANDS[index % len(_BRANDS)]
            rows.append(
                {
                    "id": uuid5(OFF_NAMESPACE, f"bench:{index}"),
                    "name": f"{brand} {head} {tail} {index}",
                    "owner_user_id": None,
                    "source": "off",
                    "trust_tier": 3,
                    "calories_per_100g": Decimal("100"),
                    "protein_per_100g": Decimal("5"),
                    "carbs_per_100g": Decimal("15"),
                    "fat_per_100g": Decimal("2"),
                    "alcohol_per_100g": Decimal("0"),
                    "is_verified": False,
                    "is_liquid": False,
                }
            )

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from coresync.infrastructure.database.models.nutrition import FoodModel

        for start in range(0, len(rows), 1000):
            stmt = pg_insert(FoodModel).values(rows[start : start + 1000])
            await session.execute(stmt.on_conflict_do_nothing(index_elements=["id"]))
        await session.commit()

        # ANALYZE, or the planner works from stale statistics and may sequential-scan a
        # table it would otherwise index — which would measure the wrong thing.
        await session.execute(text("ANALYZE foods"))
        await session.commit()

    await engine.dispose()
    return postgres_url


async def _measure(session: AsyncSession, user_id, query: str, iterations: int) -> list[float]:
    repository = SqlAlchemyFoodRepository(session)
    timings = []
    for _ in range(iterations):
        started = time.perf_counter()
        await repository.search(query=query, user_id=user_id, limit=25, offset=0)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


class TestSearchLatency:
    async def test_p95_is_within_budget(self, loaded_catalogue: str) -> None:
        engine = create_async_engine(loaded_catalogue)
        factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
        user_id = uuid7()

        timings: list[float] = []
        async with factory() as session:
            # One warm-up query per term: the first execution of a prepared statement
            # includes planning, and a benchmark that measures planning once and
            # execution fifty-nine times is measuring the wrong thing.
            for query in QUERIES:
                await _measure(session, user_id, query, 1)
            for query in QUERIES:
                timings += await _measure(session, user_id, query, ITERATIONS // len(QUERIES))

        await engine.dispose()

        timings.sort()
        p50 = statistics.median(timings)
        p95 = timings[int(len(timings) * 0.95)]

        # Printed unconditionally: a green gate that never reports its margin is one
        # nobody notices creeping toward the limit.
        print(
            f"\nfood search over {CATALOGUE_SIZE} rows — "
            f"p50 {p50:.1f}ms  p95 {p95:.1f}ms  max {timings[-1]:.1f}ms "
            f"(budget {P95_BUDGET_MS:.0f}ms)"
        )

        assert p95 < P95_BUDGET_MS, (
            f"p95 {p95:.1f}ms exceeds the {P95_BUDGET_MS:.0f}ms budget from docs/15. "
            f"p50 was {p50:.1f}ms over {CATALOGUE_SIZE} rows."
        )

    async def test_an_accented_query_is_no_slower_than_an_unaccented_one(
        self, loaded_catalogue: str
    ) -> None:
        """`unaccent` is applied on both sides, so the index is usable either way.

        If the wrapper were missing from the query side, this is where it would show:
        the unaccented form would fall back to a sequential scan and be dramatically
        slower, long before anyone noticed the results were also wrong.
        """
        engine = create_async_engine(loaded_catalogue)
        factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
        user_id = uuid7()

        async with factory() as session:
            await _measure(session, user_id, "γάλα", 3)
            accented = statistics.median(await _measure(session, user_id, "γάλα", 15))
            unaccented = statistics.median(await _measure(session, user_id, "γαλα", 15))

        await engine.dispose()

        print(f"\naccented {accented:.1f}ms  unaccented {unaccented:.1f}ms")
        # Generous ratio: the point is to catch a sequential scan, which is an order of
        # magnitude, not to police normal variance on a developer laptop.
        assert unaccented < max(accented * 4, 50.0)

    async def test_an_empty_query_is_fast(self, loaded_catalogue: str) -> None:
        """The search screen opens before anyone types, and it opens on this query."""
        engine = create_async_engine(loaded_catalogue)
        factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
        user_id = uuid7()

        async with factory() as session:
            await _measure(session, user_id, "", 3)
            timings = sorted(await _measure(session, user_id, "", 30))

        await engine.dispose()

        p95 = timings[int(len(timings) * 0.95)]
        print(f"\nempty query — p95 {p95:.1f}ms")
        assert p95 < P95_BUDGET_MS
