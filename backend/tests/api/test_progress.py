"""Weight, measurements, statistics and the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.api.conftest import auth_header, exercise_id_for, register_and_verify
from tests.fakes import CapturingEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture
async def headers(client: AsyncClient, email_sender: CapturingEmailSender) -> dict[str, str]:
    return auth_header(await register_and_verify(client, email_sender))


def days_ago(count: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=count)).isoformat()


async def log_weight(client: AsyncClient, headers: dict[str, str], **body) -> dict:
    response = await client.post("/v1/progress/weight", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestWeightLogging:
    async def test_first_weigh_in_seeds_the_trend(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        logged = await log_weight(client, headers, weightKg="80.00")
        assert logged["weightKg"] == "80.00"
        assert logged["trendWeightKg"] == "80.00"

    async def test_the_trend_lags_behind_a_jump(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """A salty dinner must not look like 2 kg of gain."""
        await log_weight(client, headers, weightKg="80.00", localDate=days_ago(1))
        second = await log_weight(client, headers, weightKg="82.00", localDate=days_ago(0))
        assert second["weightKg"] == "82.00"
        assert second["trendWeightKg"] == "80.20"

    async def test_relogging_a_day_corrects_it(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """One weigh-in per day: multiple daily weights are noise that corrupts the trend."""
        today = days_ago(0)
        await log_weight(client, headers, weightKg="80.00", localDate=today)
        await log_weight(client, headers, weightKg="81.00", localDate=today)

        series = await client.get("/v1/progress/weight", headers=headers)
        points = series.json()["points"]
        assert len(points) == 1
        assert points[0]["weightKg"] == "81.00"

    async def test_a_backfilled_weigh_in_rebuilds_the_whole_trend(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """The EWMA is path-dependent, so a late entry changes every value after it."""
        await log_weight(client, headers, weightKg="80.00", localDate=days_ago(10))
        await log_weight(client, headers, weightKg="79.00", localDate=days_ago(0))
        before = (await client.get("/v1/progress/weight", headers=headers)).json()
        latest_before = before["latestTrendKg"]

        # Insert a reading between the two.
        await log_weight(client, headers, weightKg="85.00", localDate=days_ago(5))

        after = (await client.get("/v1/progress/weight", headers=headers)).json()
        assert len(after["points"]) == 3
        assert after["latestTrendKg"] != latest_before

    async def test_an_implausible_weight_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """A pounds-for-kilograms mix-up is the common case."""
        response = await client.post(
            "/v1/progress/weight", json={"weightKg": "800.00"}, headers=headers
        )
        assert response.status_code == 400

    async def test_a_future_weigh_in_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        future = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()
        response = await client.post(
            "/v1/progress/weight",
            json={"weightKg": "80.00", "localDate": future},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_deleting_a_weigh_in_recalculates_the_trend(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await log_weight(client, headers, weightKg="80.00", localDate=days_ago(2))
        middle = await log_weight(client, headers, weightKg="90.00", localDate=days_ago(1))
        await log_weight(client, headers, weightKg="80.00", localDate=days_ago(0))

        with_outlier = (await client.get("/v1/progress/weight", headers=headers)).json()
        assert (
            await client.delete(f"/v1/progress/weight/{middle['id']}", headers=headers)
        ).status_code == 204
        without = (await client.get("/v1/progress/weight", headers=headers)).json()

        assert len(without["points"]) == 2
        assert without["latestTrendKg"] != with_outlier["latestTrendKg"]

    async def test_weekly_rate_appears_once_there_is_a_week_of_data(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        for offset in range(14, -1, -1):
            weight = 80 - (14 - offset) * 0.1
            await log_weight(client, headers, weightKg=f"{weight:.2f}", localDate=days_ago(offset))
        series = (await client.get("/v1/progress/weight", headers=headers)).json()
        assert series["weeklyRateKg"] is not None
        assert float(series["weeklyRateKg"]) < 0

    async def test_series_returns_raw_and_trend_together(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await log_weight(client, headers, weightKg="80.00", localDate=days_ago(1))
        await log_weight(client, headers, weightKg="81.00", localDate=days_ago(0))
        series = (await client.get("/v1/progress/weight", headers=headers)).json()
        for point in series["points"]:
            assert "weightKg" in point
            assert "trendKg" in point

    async def test_weight_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/progress/weight")).status_code == 401


class TestMeasurements:
    async def test_record_and_read_back(self, client: AsyncClient, headers: dict[str, str]) -> None:
        response = await client.post(
            "/v1/progress/measurements",
            json={"waist": "82.50", "chest": "104.00", "leftArm": "38.00"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["sites"]["waist"] == "82.50"
        assert body["sites"]["left_arm"] == "38.00"

    async def test_waist_to_hip_ratio_is_derived(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/progress/measurements",
            json={"waist": "80.00", "hips": "100.00"},
            headers=headers,
        )
        assert response.json()["waistToHipRatio"] == "0.80"

    async def test_omitted_sites_keep_their_previous_value(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """ "I did not measure my calves today" is not "my calves are now unknown"."""
        today = days_ago(0)
        await client.post(
            "/v1/progress/measurements",
            json={"waist": "82.00", "leftCalf": "38.00", "localDate": today},
            headers=headers,
        )
        second = await client.post(
            "/v1/progress/measurements",
            json={"waist": "81.00", "localDate": today},
            headers=headers,
        )
        sites = second.json()["sites"]
        assert sites["waist"] == "81.00"
        assert sites["left_calf"] == "38.00"

    async def test_one_row_per_day(self, client: AsyncClient, headers: dict[str, str]) -> None:
        today = days_ago(0)
        first = await client.post(
            "/v1/progress/measurements",
            json={"waist": "82.00", "localDate": today},
            headers=headers,
        )
        second = await client.post(
            "/v1/progress/measurements",
            json={"waist": "81.00", "localDate": today},
            headers=headers,
        )
        assert first.json()["id"] == second.json()["id"]

        history = await client.get("/v1/progress/measurements", headers=headers)
        assert len(history.json()) == 1

    async def test_an_empty_payload_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.post("/v1/progress/measurements", json={}, headers=headers)
        assert response.status_code == 400

    async def test_an_out_of_range_value_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """A chest of 32 cm is inches mistaken for centimetres."""
        response = await client.post(
            "/v1/progress/measurements", json={"chest": "32.00"}, headers=headers
        )
        assert response.status_code == 400

    async def test_series_reports_change_per_site(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await client.post(
            "/v1/progress/measurements",
            json={"waist": "85.00", "localDate": days_ago(30)},
            headers=headers,
        )
        await client.post(
            "/v1/progress/measurements",
            json={"waist": "82.00", "localDate": days_ago(0)},
            headers=headers,
        )
        response = await client.get(
            "/v1/progress/measurements/series", params={"site": "waist"}, headers=headers
        )
        trends = response.json()["trends"]
        assert len(trends) == 1
        assert trends[0]["site"] == "waist"
        assert trends[0]["changeCm"] == "-3.00"
        assert len(trends[0]["points"]) == 2

    async def test_series_omits_sites_never_measured(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        await client.post("/v1/progress/measurements", json={"waist": "82.00"}, headers=headers)
        response = await client.get("/v1/progress/measurements/series", headers=headers)
        assert [t["site"] for t in response.json()["trends"]] == ["waist"]

    async def test_delete_a_measurement(self, client: AsyncClient, headers: dict[str, str]) -> None:
        created = await client.post(
            "/v1/progress/measurements", json={"waist": "82.00"}, headers=headers
        )
        entry_id = created.json()["id"]
        assert (
            await client.delete(f"/v1/progress/measurements/{entry_id}", headers=headers)
        ).status_code == 204
        assert (await client.get("/v1/progress/measurements", headers=headers)).json() == []

    async def test_deleting_a_missing_measurement_is_404(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.delete(
            "/v1/progress/measurements/0192f8e0-7b3a-7c4d-9e2f-000000000000", headers=headers
        )
        assert response.status_code == 404


class TestStatistics:
    async def _complete_workout(
        self, client: AsyncClient, headers: dict[str, str], bench_id: str
    ) -> None:
        session = await client.post("/v1/workouts/sessions", json={}, headers=headers)
        session_id = session.json()["id"]
        added = await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises",
            json={"exerciseId": bench_id},
            headers=headers,
        )
        entry_id = added.json()["exercises"][0]["id"]
        await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}/sets",
            json={"reps": 8, "weightKg": "100"},
            headers=headers,
        )
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

    async def test_volume_by_muscle_group(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        bench_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        await self._complete_workout(client, headers, bench_id)

        response = await client.get("/v1/progress/stats/volume", headers=headers)
        assert response.status_code == 200
        buckets = response.json()
        assert len(buckets) == 1
        split = buckets[0]["volumeByMuscleGroup"]
        # A bench press trains chest primarily and arms/shoulders as secondaries, so the
        # tonnage must be split rather than attributed wholly to chest.
        assert "chest" in split
        assert len(split) > 1
        assert buckets[0]["totalSets"] == 1

    async def test_volume_buckets_by_month(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        bench_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        await self._complete_workout(client, headers, bench_id)
        response = await client.get(
            "/v1/progress/stats/volume", params={"granularity": "month"}, headers=headers
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_frequency(self, client: AsyncClient, headers: dict[str, str]) -> None:
        bench_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        await self._complete_workout(client, headers, bench_id)

        response = await client.get("/v1/progress/stats/frequency", headers=headers)
        buckets = response.json()
        assert len(buckets) == 1
        assert buckets[0]["workoutCount"] == 1
        assert buckets[0]["totalVolumeKg"] == "800.00"

    async def test_records_list(self, client: AsyncClient, headers: dict[str, str]) -> None:
        bench_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        await self._complete_workout(client, headers, bench_id)

        response = await client.get("/v1/progress/stats/records", headers=headers)
        records = response.json()
        assert {r["recordType"] for r in records} == {
            "max_weight",
            "max_reps",
            "max_volume_set",
            "est_1rm",
        }
        assert all(r["exerciseName"] == "Barbell Bench Press" for r in records)

    async def test_an_oversized_window_is_refused(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/v1/progress/stats/frequency",
            params={"from": "2015-01-01", "to": days_ago(0)},
            headers=headers,
        )
        assert response.status_code == 400

    async def test_stats_are_empty_for_a_new_user(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        assert (await client.get("/v1/progress/stats/volume", headers=headers)).json() == []
        assert (await client.get("/v1/progress/stats/frequency", headers=headers)).json() == []
        assert (await client.get("/v1/progress/stats/records", headers=headers)).json() == []


class TestDashboard:
    async def test_dashboard_bundles_everything(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        bench_id = await exercise_id_for(client, headers, "Barbell Bench Press")
        await log_weight(client, headers, weightKg="80.00")
        await client.post("/v1/progress/measurements", json={"waist": "82.00"}, headers=headers)

        session = await client.post("/v1/workouts/sessions", json={}, headers=headers)
        session_id = session.json()["id"]
        added = await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises",
            json={"exerciseId": bench_id},
            headers=headers,
        )
        entry_id = added.json()["exercises"][0]["id"]
        await client.post(
            f"/v1/workouts/sessions/{session_id}/exercises/{entry_id}/sets",
            json={"reps": 8, "weightKg": "100"},
            headers=headers,
        )
        await client.post(f"/v1/workouts/sessions/{session_id}/complete", json={}, headers=headers)

        response = await client.get("/v1/progress/stats/overview", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["weight"]["latestWeightKg"] == "80.00"
        assert body["workoutStreak"]["current"] == 1
        assert body["thisWeek"]["workoutCount"] == 1
        assert body["thisWeek"]["totalVolumeKg"] == "800.00"
        assert body["thisWeek"]["prCount"] == 4
        assert body["latestMeasurement"]["sites"]["waist"] == "82.00"
        assert len(body["recentRecords"]) == 4
        # Nutrition is null, not zeroes: the client must show "not tracked" rather than
        # claiming the user ate nothing.
        assert body["nutrition"] is None

    async def test_dashboard_works_for_a_brand_new_user(
        self, client: AsyncClient, headers: dict[str, str]
    ) -> None:
        """The empty state is the first thing every user sees."""
        response = await client.get("/v1/progress/stats/overview", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["weight"]["points"] == []
        assert body["weight"]["latestWeightKg"] is None
        assert body["workoutStreak"]["current"] == 0
        assert body["thisWeek"]["workoutCount"] == 0
        assert body["latestMeasurement"] is None
        assert body["recentRecords"] == []

    async def test_dashboard_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/progress/stats/overview")).status_code == 401


class TestProgressAuthorizationBoundary:
    async def test_weight_and_measurements_are_private(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="progress-owner@example.com")
        )
        weight = await log_weight(client, owner, weightKg="80.00")
        measurement = await client.post(
            "/v1/progress/measurements", json={"waist": "82.00"}, headers=owner
        )

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="progress-thief@example.com")
        )

        # The intruder sees none of the owner's data.
        assert (await client.get("/v1/progress/weight", headers=intruder)).json()["points"] == []
        assert (await client.get("/v1/progress/measurements", headers=intruder)).json() == []

        # And cannot delete it. A scoped delete simply matches nothing.
        await client.delete(f"/v1/progress/weight/{weight['id']}", headers=intruder)
        assert (
            await client.delete(
                f"/v1/progress/measurements/{measurement.json()['id']}", headers=intruder
            )
        ).status_code == 404

        # The owner's data survives the attempt.
        assert len((await client.get("/v1/progress/weight", headers=owner)).json()["points"]) == 1
        assert len((await client.get("/v1/progress/measurements", headers=owner)).json()) == 1

    async def test_dashboard_is_scoped_to_the_caller(
        self, client: AsyncClient, email_sender: CapturingEmailSender
    ) -> None:
        owner = auth_header(
            await register_and_verify(client, email_sender, email="dash-owner@example.com")
        )
        await log_weight(client, owner, weightKg="80.00")

        intruder = auth_header(
            await register_and_verify(client, email_sender, email="dash-other@example.com")
        )
        body = (await client.get("/v1/progress/stats/overview", headers=intruder)).json()
        assert body["weight"]["latestWeightKg"] is None
