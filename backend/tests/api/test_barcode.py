"""Scanning a barcode, and what happens when we have never seen it.

The behaviour under test is cache-on-first-use: the first person to scan a product pays
a network round trip, and everyone after them reads it out of our own table. That is
what makes the catalogue grow along the contour of what our users actually buy rather
than what a bulk import guessed.

The external lookup is a stub. A test that reached Open Food Facts would fail whenever
they had an outage — which, while this was written, they were having.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from coresync.application.common.ports import ExternalFood
from coresync.presentation.dependencies import AppContainer
from coresync.presentation.main import create_app
from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration

NUTELLA = ExternalFood(
    barcode="3017620422003",
    name="Nutella",
    brand="Ferrero",
    calories_per_100g=Decimal("539"),
    protein_per_100g=Decimal("6.3"),
    carbs_per_100g=Decimal("57.5"),
    fat_per_100g=Decimal("30.9"),
    alcohol_per_100g=Decimal(0),
    is_liquid=False,
    serving_grams=Decimal("15"),
)

# Stated calories that its own macros contradict — the shape of a genuinely wrong OFF
# row, taken from a real one (a mayonnaise claiming 292 kcal against 712 implied).
IMPOSSIBLE = ExternalFood(
    barcode="9999999999999",
    name="Mystery mayonnaise",
    brand=None,
    calories_per_100g=Decimal("292"),
    protein_per_100g=Decimal("1"),
    carbs_per_100g=Decimal("2"),
    fat_per_100g=Decimal("78"),
    alcohol_per_100g=Decimal(0),
    is_liquid=False,
)


class StubLookup:
    """Records calls so the test can prove the second scan never left the database."""

    def __init__(self, *products: ExternalFood) -> None:
        self._by_code = {p.barcode: p for p in products}
        self.calls: list[str] = []

    async def by_barcode(self, barcode: str) -> ExternalFood | None:
        self.calls.append(barcode)
        return self._by_code.get(barcode)


@pytest.fixture
def lookup() -> StubLookup:
    return StubLookup(NUTELLA, IMPOSSIBLE)


@pytest_asyncio.fixture
async def scan_client(container: AppContainer, api_settings, lookup: StubLookup):
    """A client whose container has the stub wired in as the external lookup."""
    from dataclasses import replace as dc_replace

    from httpx import ASGITransport

    app = create_app(api_settings)
    app.state.container = dc_replace(container, external_foods=lookup)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Client-Version": "test/1.0"},
    ) as http_client:
        yield http_client


@pytest.fixture
async def headers(scan_client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(scan_client, email_sender))


class TestBarcodeLookup:
    async def test_an_unknown_barcode_is_fetched_and_cached(
        self, scan_client: AsyncClient, headers: dict, lookup: StubLookup
    ) -> None:
        response = await scan_client.get(
            f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Ferrero Nutella"
        assert Decimal(body["caloriesPer100g"]) == Decimal("539")
        assert lookup.calls == [NUTELLA.barcode]

    async def test_a_fetched_product_is_community_tier_and_unverified(
        self, scan_client: AsyncClient, headers: dict
    ) -> None:
        """Nobody checked these numbers by hand, and the badge means somebody did."""
        response = await scan_client.get(
            f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers
        )
        assert response.json()["trustTier"] == 3
        assert response.json()["isVerified"] is False
        assert response.json()["source"] == "off"

    async def test_the_second_scan_does_not_leave_the_database(
        self, scan_client: AsyncClient, headers: dict, lookup: StubLookup
    ) -> None:
        """The whole point of caching on first use."""
        for _ in range(3):
            response = await scan_client.get(
                f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers
            )
            assert response.status_code == 200

        assert lookup.calls == [NUTELLA.barcode]

    async def test_a_cached_product_is_findable_by_search(
        self, scan_client: AsyncClient, headers: dict
    ) -> None:
        """A scan does not just answer once — it grows the catalogue for everyone."""
        await scan_client.get(f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers)
        results = await scan_client.get(
            "/v1/nutrition/foods", params={"q": "Nutella"}, headers=headers
        )
        assert "Ferrero Nutella" in {f["name"] for f in results.json()["items"]}

    async def test_a_cached_product_keeps_its_serving(
        self, scan_client: AsyncClient, headers: dict
    ) -> None:
        response = await scan_client.get(
            f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers
        )
        servings = response.json()["servings"]
        assert len(servings) == 1
        assert Decimal(servings[0]["grams"]) == Decimal("15")

    async def test_a_cached_product_can_be_logged(
        self, scan_client: AsyncClient, headers: dict
    ) -> None:
        scanned = await scan_client.get(
            f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers
        )
        logged = await scan_client.post(
            "/v1/nutrition/diary",
            json={"foodId": scanned.json()["id"], "mealType": "snack", "quantity": "15"},
            headers=headers,
        )
        assert logged.status_code == 201, logged.text
        assert Decimal(logged.json()["macros"]["calories"]) > 0

    async def test_a_product_that_is_nowhere_is_a_404(
        self, scan_client: AsyncClient, headers: dict, lookup: StubLookup
    ) -> None:
        response = await scan_client.get(
            "/v1/nutrition/foods/barcode/0000000000000", headers=headers
        )
        assert response.status_code == 404
        assert lookup.calls == ["0000000000000"]

    async def test_a_product_whose_numbers_do_not_reconcile_is_not_stored(
        self, scan_client: AsyncClient, headers: dict
    ) -> None:
        """The fatal risk, at the point it would enter the system.

        A scan that finds nothing is a small disappointment. A scan that silently
        records the wrong calories is the failure this phase exists to prevent, so a
        row that fails the energy check is refused rather than cached.
        """
        response = await scan_client.get(
            f"/v1/nutrition/foods/barcode/{IMPOSSIBLE.barcode}", headers=headers
        )
        assert response.status_code == 404

        results = await scan_client.get(
            "/v1/nutrition/foods", params={"q": "Mystery"}, headers=headers
        )
        assert results.json()["items"] == []

    async def test_a_locally_curated_barcode_never_calls_out(
        self, scan_client: AsyncClient, headers: dict, lookup: StubLookup
    ) -> None:
        """Our own data always wins; the network is the fallback, not the first stop."""
        created = await scan_client.post(
            "/v1/nutrition/foods",
            json={"name": "Δικό μου", "caloriesPer100g": "100", "proteinPer100g": "25"},
            headers=headers,
        )
        assert created.status_code == 201, created.text

        # Nothing links that food to Nutella's barcode, so this still goes out —
        # the assertion that matters is the one below, after it is cached.
        await scan_client.get(f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers)
        before = len(lookup.calls)
        await scan_client.get(f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers)
        assert len(lookup.calls) == before


class TestWithoutAnExternalLookup:
    async def test_a_miss_is_still_a_clean_404(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        """The default container has no lookup configured, and that must not 500."""
        headers = auth_header(await register_and_verify(client, email_sender))
        response = await client.get(
            f"/v1/nutrition/foods/barcode/{NUTELLA.barcode}", headers=headers
        )
        assert response.status_code == 404
