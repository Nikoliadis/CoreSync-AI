"""Daily summaries and the nutrition streak.

The summary table is derived data, written in the same transaction as the change that
caused it. The tests that matter are the ones proving it cannot drift: after a log, an
edit, a move between days, a delete and a copy, the summary must still agree with the
entries it claims to summarise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


@pytest.fixture
async def other_headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(
        await register_and_verify(client, email_sender, email="intruder@example.com")
    )


def days_ago(count: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=count)).isoformat()


async def food_named(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.get("/v1/nutrition/foods", params={"q": name}, headers=headers)
    assert response.status_code == 200, response.text
    match = next((f for f in response.json()["items"] if f["name"] == name), None)
    assert match is not None, f"seeded food '{name}' not found"
    return match


async def log(client: AsyncClient, headers: dict[str, str], **body: object) -> dict:
    response = await client.post("/v1/nutrition/diary", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def history(client: AsyncClient, headers: dict[str, str], days: int = 30) -> list[dict]:
    response = await client.get("/v1/nutrition/history", params={"days": days}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def day(items: list[dict], iso: str) -> dict | None:
    return next((i for i in items if i["localDate"] == iso), None)


class TestSummariesFollowTheDiary:
    async def test_logging_writes_a_summary(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert Decimal(today["calories"]) == Decimal("155")
        assert today["entryCount"] == 1

    async def test_a_second_entry_adds_to_the_same_day(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        feta = await food_named(client, headers, "Φέτα")
        await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        await log(client, headers, foodId=feta["id"], mealType="lunch", quantity="100")

        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert today["entryCount"] == 2
        assert Decimal(today["calories"]) == Decimal("419")

    async def test_editing_an_amount_updates_the_summary(
        self, client: AsyncClient, headers: dict
    ) -> None:
        chicken = await food_named(client, headers, "Στήθος κοτόπουλο ωμό")
        entry = await log(client, headers, foodId=chicken["id"], mealType="lunch", quantity="200")

        await client.patch(
            f"/v1/nutrition/diary/{entry['id']}", json={"quantity": "100"}, headers=headers
        )
        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert Decimal(today["calories"]) == Decimal("165")

    async def test_moving_an_entry_refreshes_both_days(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The case an incremental update would get wrong.

        Refreshing only the destination would leave the source day still claiming the
        calories that walked away from it.
        """
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        yesterday = days_ago(1)
        await client.patch(
            f"/v1/nutrition/diary/{entry['id']}",
            json={"localDate": yesterday},
            headers=headers,
        )

        items = await history(client, headers)
        source = day(items, days_ago(0))
        destination = day(items, yesterday)

        assert source is None or Decimal(source["calories"]) == Decimal(0)
        assert destination is not None
        assert Decimal(destination["calories"]) == Decimal("155")

    async def test_deleting_the_last_entry_zeroes_the_day(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        entry = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        await client.delete(f"/v1/nutrition/diary/{entry['id']}", headers=headers)

        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert Decimal(today["calories"]) == Decimal(0)
        assert today["entryCount"] == 0

    async def test_copying_a_day_summarises_the_target(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        yesterday = days_ago(1)
        await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="100",
            localDate=yesterday,
        )
        await client.post(
            "/v1/nutrition/diary/copy",
            json={"sourceDate": yesterday, "targetDate": days_ago(0)},
            headers=headers,
        )

        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert today["entryCount"] == 1

    async def test_water_lands_in_the_summary(self, client: AsyncClient, headers: dict) -> None:
        await client.post("/v1/nutrition/water", json={"millilitres": "500"}, headers=headers)
        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert Decimal(today["waterMl"]) == Decimal("500")

    async def test_a_quick_add_counts_as_a_logged_day(
        self, client: AsyncClient, headers: dict
    ) -> None:
        await client.post(
            "/v1/nutrition/diary/quick-add",
            json={"mealType": "dinner", "calories": "650"},
            headers=headers,
        )
        today = day(await history(client, headers), days_ago(0))
        assert today is not None
        assert today["entryCount"] == 1

    async def test_the_summary_matches_the_diary_it_summarises(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The invariant, stated directly, after a run of every kind of change."""
        egg = await food_named(client, headers, "Αυγό")
        feta = await food_named(client, headers, "Φέτα")

        first = await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        await log(client, headers, foodId=feta["id"], mealType="lunch", quantity="50")
        await client.patch(
            f"/v1/nutrition/diary/{first['id']}", json={"quantity": "200"}, headers=headers
        )
        await client.post(
            "/v1/nutrition/diary/quick-add",
            json={"mealType": "snack", "calories": "120"},
            headers=headers,
        )

        diary = await client.get("/v1/nutrition/diary", headers=headers)
        summary = day(await history(client, headers), days_ago(0))
        assert summary is not None
        assert Decimal(summary["calories"]) == Decimal(diary.json()["totals"]["calories"])
        assert summary["entryCount"] == len(diary.json()["entries"])


class TestHistoryRange:
    async def test_only_days_with_something_logged_appear(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """Absent is not zero: 'ate nothing' and 'logged nothing' are different facts."""
        egg = await food_named(client, headers, "Αυγό")
        await log(
            client,
            headers,
            foodId=egg["id"],
            mealType="breakfast",
            quantity="100",
            localDate=days_ago(3),
        )
        items = await history(client, headers)
        assert [i["localDate"] for i in items] == [days_ago(3)]

    async def test_the_range_is_bounded_by_days(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        for offset in (0, 20):
            await log(
                client,
                headers,
                foodId=egg["id"],
                mealType="breakfast",
                quantity="100",
                localDate=days_ago(offset),
            )

        recent = await history(client, headers, days=7)
        assert [i["localDate"] for i in recent] == [days_ago(0)]

        wider = await history(client, headers, days=30)
        assert len(wider) == 2

    async def test_history_is_per_user(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")
        assert await history(client, other_headers) == []


class TestNutritionStreak:
    async def test_no_logging_is_no_streak(self, client: AsyncClient, headers: dict) -> None:
        response = await client.get("/v1/nutrition/streak", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["current"] == 0
        assert response.json()["lastDate"] is None

    async def test_consecutive_days_count(self, client: AsyncClient, headers: dict) -> None:
        egg = await food_named(client, headers, "Αυγό")
        for offset in (0, 1, 2):
            await log(
                client,
                headers,
                foodId=egg["id"],
                mealType="breakfast",
                quantity="100",
                localDate=days_ago(offset),
            )

        response = await client.get("/v1/nutrition/streak", headers=headers)
        assert response.json()["current"] == 3
        assert response.json()["longest"] == 3

    async def test_a_gap_breaks_the_current_streak_but_keeps_the_record(
        self, client: AsyncClient, headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        for offset in (5, 6, 7, 8):
            await log(
                client,
                headers,
                foodId=egg["id"],
                mealType="breakfast",
                quantity="100",
                localDate=days_ago(offset),
            )

        response = await client.get("/v1/nutrition/streak", headers=headers)
        assert response.json()["current"] == 0
        assert response.json()["longest"] == 4

    async def test_a_zero_calorie_day_still_counts(
        self, client: AsyncClient, headers: dict
    ) -> None:
        """The reason the streak counts entries rather than calories.

        Black coffee is a logged day. A streak that punishes honest logging teaches
        people to log dishonestly.
        """
        coffee = await food_named(client, headers, "Ελληνικός καφές σκέτος")
        await log(client, headers, foodId=coffee["id"], mealType="breakfast", quantity="60")

        response = await client.get("/v1/nutrition/streak", headers=headers)
        assert response.json()["current"] == 1

    async def test_streaks_are_per_user(
        self, client: AsyncClient, headers: dict, other_headers: dict
    ) -> None:
        egg = await food_named(client, headers, "Αυγό")
        await log(client, headers, foodId=egg["id"], mealType="breakfast", quantity="100")

        response = await client.get("/v1/nutrition/streak", headers=other_headers)
        assert response.json()["current"] == 0
