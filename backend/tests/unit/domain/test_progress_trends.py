"""Weight trends, goal projection, measurements and the photo domain.

The EWMA rules matter more than they look: a lifter who sees their raw morning weight
jump 1.5 kg after a salty dinner concludes the app is wrong, or that they are. The trend
is the number that tells the truth, and it has to behave predictably.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from coresync.core.ids import uuid7
from coresync.domain.progress.entities import WeightLog, WeightSource
from coresync.domain.progress.measurements import (
    SITE_RANGE_CM,
    BodyMeasurement,
    MeasurementSite,
)
from coresync.domain.progress.photos import (
    MAX_UPLOAD_BYTES,
    PhotoComparison,
    PhotoPose,
    PhotoVisibility,
    ProcessingStatus,
    ProgressPhoto,
    blob_path_for,
    thumbnail_path_for,
)
from coresync.domain.progress.services import (
    GoalProjector,
    MeasurementTrendCalculator,
    WeightTrendCalculator,
)

USER = uuid7()
START = date(2026, 1, 1)


def series(*weights: str, start: date = START, step_days: int = 1) -> list[WeightLog]:
    return [
        WeightLog.create(
            user_id=USER,
            local_date=start + timedelta(days=index * step_days),
            weight_kg=Decimal(value),
            source=WeightSource.MANUAL,
        )
        for index, value in enumerate(weights)
    ]


class TestWeightTrendCalculator:
    def setup_method(self) -> None:
        self.calculator = WeightTrendCalculator()

    def test_first_reading_seeds_the_trend(self) -> None:
        trend = self.calculator.build(series("80"))
        assert trend.points[0].trend_kg == Decimal("80.00")
        assert trend.latest_trend_kg == Decimal("80.00")

    def test_trend_lags_behind_a_jump(self) -> None:
        """A single heavy morning must move the trend by a fraction, not fully."""
        trend = self.calculator.build(series("80", "82"))
        # 80 + 0.1 x (82 - 80) = 80.2
        assert trend.points[1].trend_kg == Decimal("80.20")
        assert trend.points[1].weight_kg == Decimal("82")

    def test_trend_converges_towards_a_sustained_change(self) -> None:
        trend = self.calculator.build(series(*(["85"] * 60), start=START))
        # Starting at 85 it stays at 85; the interesting case is approaching from below.
        rising = self.calculator.build(series("80", *(["85"] * 60)))
        assert rising.latest_trend_kg is not None
        assert Decimal("84") < rising.latest_trend_kg <= Decimal("85")
        assert trend.latest_trend_kg == Decimal("85.00")

    def test_empty_series_is_not_an_error(self) -> None:
        trend = self.calculator.build([])
        assert not trend.has_data
        assert trend.latest_trend_kg is None
        assert trend.weekly_rate_kg is None

    def test_recalculation_is_order_independent(self) -> None:
        """A backfilled weigh-in must produce the same trend as if logged in order."""
        ordered = series("80", "80.5", "81")
        shuffled = [ordered[2], ordered[0], ordered[1]]

        in_order = [p.trend_kg for p in self.calculator.build(list(ordered)).points]
        out_of_order = [p.trend_kg for p in self.calculator.build(shuffled).points]

        assert in_order == out_of_order

    def test_weekly_rate_needs_a_week(self) -> None:
        """Extrapolating a weekly rate from three days is extrapolating noise."""
        assert self.calculator.build(series("80", "79.8", "79.6")).weekly_rate_kg is None

    def test_weekly_rate_over_a_real_window(self) -> None:
        logs = series(*[str(Decimal("80") - Decimal("0.1") * index) for index in range(15)])
        trend = self.calculator.build(logs)
        assert trend.weekly_rate_kg is not None
        # Losing weight, so the rate must be negative.
        assert trend.weekly_rate_kg < 0

    def test_change_is_measured_on_the_trend_not_the_raw_values(self) -> None:
        """A dehydrated final morning must not invent progress."""
        logs = series("80", "80", "80", "78")
        trend = self.calculator.build(logs)
        assert trend.change_kg is not None
        # Raw change is -2 kg; the trend has barely moved.
        assert trend.change_kg > Decimal("-1")

    @given(
        weights=st.lists(
            st.decimals(min_value=Decimal("40"), max_value=Decimal("200"), places=1),
            min_size=1,
            max_size=40,
        )
    )
    def test_trend_always_stays_within_the_observed_range(self, weights: list[Decimal]) -> None:
        """An EWMA is a weighted average, so it can never leave the data's bounds."""
        logs = series(*[str(w) for w in weights])
        trend = self.calculator.build(logs)
        low, high = min(weights), max(weights)
        for point in trend.points:
            assert low - Decimal("0.01") <= point.trend_kg <= high + Decimal("0.01")


class TestGoalProjector:
    def setup_method(self) -> None:
        self.projector = GoalProjector()
        self.today = date(2026, 3, 1)

    def test_projects_a_date_when_closing_the_gap(self) -> None:
        projection = self.projector.project(
            current_trend_kg=Decimal("85"),
            target_weight_kg=Decimal("80"),
            weekly_rate_kg=Decimal("-0.5"),
            today=self.today,
        )
        assert projection is not None
        assert projection.weeks_remaining == Decimal("10.0")
        assert projection.projected_date == self.today + timedelta(days=70)
        assert not projection.is_moving_away

    def test_refuses_to_project_when_moving_away(self) -> None:
        """A cheerful date computed from a trend heading the wrong way is worse than none."""
        projection = self.projector.project(
            current_trend_kg=Decimal("85"),
            target_weight_kg=Decimal("80"),
            weekly_rate_kg=Decimal("0.3"),
            today=self.today,
        )
        assert projection is not None
        assert projection.is_moving_away
        assert projection.projected_date is None

    def test_a_flat_trend_projects_nothing(self) -> None:
        assert (
            self.projector.project(
                current_trend_kg=Decimal("85"),
                target_weight_kg=Decimal("80"),
                weekly_rate_kg=Decimal("0"),
                today=self.today,
            )
            is None
        )

    def test_target_already_reached(self) -> None:
        projection = self.projector.project(
            current_trend_kg=Decimal("80"),
            target_weight_kg=Decimal("80"),
            weekly_rate_kg=Decimal("-0.5"),
            today=self.today,
        )
        assert projection is not None
        assert projection.weeks_remaining == Decimal("0")
        assert projection.projected_date == self.today

    def test_an_absurdly_distant_projection_is_withheld(self) -> None:
        projection = self.projector.project(
            current_trend_kg=Decimal("120"),
            target_weight_kg=Decimal("80"),
            weekly_rate_kg=Decimal("-0.01"),
            today=self.today,
        )
        assert projection is not None
        assert projection.projected_date is None

    def test_gaining_towards_a_higher_target_also_projects(self) -> None:
        projection = self.projector.project(
            current_trend_kg=Decimal("70"),
            target_weight_kg=Decimal("75"),
            weekly_rate_kg=Decimal("0.25"),
            today=self.today,
        )
        assert projection is not None
        assert projection.weeks_remaining == Decimal("20.0")


class TestBodyMeasurement:
    def test_records_only_the_sites_given(self) -> None:
        measurement = BodyMeasurement.create(
            user_id=USER,
            local_date=START,
            sites={MeasurementSite.WAIST: Decimal("82"), MeasurementSite.CHEST: None},  # type: ignore[dict-item]
        )
        assert measurement.recorded_sites == [MeasurementSite.WAIST]

    def test_a_measurement_must_record_something(self) -> None:
        with pytest.raises(ValueError, match="at least one site"):
            BodyMeasurement.create(user_id=USER, local_date=START, sites={})

    def test_an_inches_for_centimetres_mistake_is_caught(self) -> None:
        """32 inches entered as centimetres for a chest is below any plausible range."""
        with pytest.raises(ValueError, match="outside the plausible range"):
            BodyMeasurement.create(
                user_id=USER, local_date=START, sites={MeasurementSite.CHEST: Decimal("32")}
            )

    @pytest.mark.parametrize("site", list(MeasurementSite))
    def test_every_site_has_a_declared_range(self, site: MeasurementSite) -> None:
        low, high = SITE_RANGE_CM[site]
        assert low < high

    def test_waist_to_hip_ratio(self) -> None:
        measurement = BodyMeasurement.create(
            user_id=USER,
            local_date=START,
            sites={MeasurementSite.WAIST: Decimal("80"), MeasurementSite.HIPS: Decimal("100")},
        )
        assert measurement.waist_to_hip_ratio() == Decimal("0.80")

    def test_ratio_needs_both_sites(self) -> None:
        measurement = BodyMeasurement.create(
            user_id=USER, local_date=START, sites={MeasurementSite.WAIST: Decimal("80")}
        )
        assert measurement.waist_to_hip_ratio() is None

    def test_bilateral_sites_mirror_each_other(self) -> None:
        assert MeasurementSite.LEFT_ARM.mirror is MeasurementSite.RIGHT_ARM
        assert MeasurementSite.RIGHT_CALF.mirror is MeasurementSite.LEFT_CALF
        assert MeasurementSite.WAIST.mirror is None
        assert MeasurementSite.LEFT_THIGH.is_bilateral
        assert not MeasurementSite.NECK.is_bilateral

    def test_asymmetry_is_reported_signed(self) -> None:
        """Left and right are tracked separately because averaging hides an imbalance."""
        measurement = BodyMeasurement.create(
            user_id=USER,
            local_date=START,
            sites={
                MeasurementSite.LEFT_ARM: Decimal("38"),
                MeasurementSite.RIGHT_ARM: Decimal("40"),
            },
        )
        assert measurement.asymmetry(MeasurementSite.RIGHT_ARM) == Decimal("2")
        assert measurement.asymmetry(MeasurementSite.LEFT_ARM) == Decimal("-2")

    def test_asymmetry_needs_both_sides(self) -> None:
        measurement = BodyMeasurement.create(
            user_id=USER, local_date=START, sites={MeasurementSite.LEFT_ARM: Decimal("38")}
        )
        assert measurement.asymmetry(MeasurementSite.LEFT_ARM) is None


class TestMeasurementTrendCalculator:
    def test_reports_net_change_per_site(self) -> None:
        trends = MeasurementTrendCalculator().build(
            {
                "waist": [(START, Decimal("85")), (START + timedelta(days=30), Decimal("82"))],
                "chest": [(START, Decimal("100"))],
            }
        )
        by_site = {t.site: t for t in trends}
        assert by_site["waist"].change_cm == Decimal("-3.00")
        assert by_site["chest"].change_cm == Decimal("0.00")

    def test_points_are_sorted_regardless_of_input_order(self) -> None:
        later = START + timedelta(days=10)
        trends = MeasurementTrendCalculator().build(
            {"waist": [(later, Decimal("82")), (START, Decimal("85"))]}
        )
        assert [p[0] for p in trends[0].points] == [START, later]
        assert trends[0].first_value == Decimal("85")

    def test_empty_series_are_dropped(self) -> None:
        assert MeasurementTrendCalculator().build({"waist": []}) == []


class TestProgressPhotoDomain:
    def make(self, **overrides) -> ProgressPhoto:
        defaults = {
            "user_id": USER,
            "local_date": START,
            "pose": PhotoPose.FRONT,
            "blob_path": "progress-photos/x/y.jpg",
        }
        return ProgressPhoto.create(**{**defaults, **overrides})

    def test_a_new_photo_is_private_and_pending(self) -> None:
        photo = self.make()
        assert photo.visibility is PhotoVisibility.PRIVATE
        assert photo.processing_status is ProcessingStatus.PENDING

    def test_a_pending_photo_is_not_readable(self) -> None:
        """It still carries its original EXIF, which includes where it was taken."""
        assert not self.make().is_readable

    def test_readable_only_after_the_metadata_strip_is_recorded(self) -> None:
        photo = self.make()
        photo.begin_processing()
        assert not photo.is_readable

        photo.mark_ready(
            at=datetime(2026, 1, 2, tzinfo=UTC),
            width=1080,
            height=1440,
            bytes_size=500_000,
            thumbnail_path="progress-photos/x/y_thumb.jpg",
        )
        assert photo.is_readable
        assert photo.exif_stripped_at is not None

    def test_a_failed_photo_is_not_readable(self) -> None:
        photo = self.make()
        photo.mark_failed()
        assert not photo.is_readable

    def test_ownership_check(self) -> None:
        photo = self.make()
        assert photo.is_owned_by(USER)
        assert not photo.is_owned_by(uuid7())

    def test_visibility_has_no_public_option(self) -> None:
        """There is no product reason for a progress photo to be world-readable."""
        assert {v.value for v in PhotoVisibility} == {"private", "shared_link"}

    def test_blob_path_is_user_partitioned(self) -> None:
        photo_id = uuid7()
        path = blob_path_for(user_id=USER, photo_id=photo_id, extension="jpg")
        assert path == f"progress-photos/{USER}/{photo_id}.jpg"

    @pytest.mark.parametrize("extension", ["exe", "svg", "gif", "php", ""])
    def test_unsupported_extensions_are_refused(self, extension: str) -> None:
        with pytest.raises(ValueError, match="unsupported image extension"):
            blob_path_for(user_id=USER, photo_id=uuid7(), extension=extension)

    def test_thumbnail_path_derives_from_the_original(self) -> None:
        assert thumbnail_path_for("progress-photos/u/p.png") == "progress-photos/u/p_thumb.jpg"

    def test_upload_limit_matches_the_documented_policy(self) -> None:
        assert MAX_UPLOAD_BYTES == 15 * 1024 * 1024


class TestPhotoComparison:
    def make(
        self, on: date, weight: str | None, pose: PhotoPose = PhotoPose.FRONT
    ) -> ProgressPhoto:
        return ProgressPhoto.create(
            user_id=USER,
            local_date=on,
            pose=pose,
            blob_path=f"progress-photos/u/{on}.jpg",
            weight_at_capture_kg=Decimal(weight) if weight else None,
        )

    def test_reports_days_and_weight_delta(self) -> None:
        comparison = PhotoComparison(
            earlier=self.make(START, "78.2"),
            later=self.make(START + timedelta(days=90), "75.6"),
        )
        assert comparison.days_between == 90
        assert comparison.weight_delta_kg == Decimal("-2.6")
        assert comparison.poses_match

    def test_missing_weight_yields_no_delta(self) -> None:
        comparison = PhotoComparison(
            earlier=self.make(START, None),
            later=self.make(START + timedelta(days=30), "75"),
        )
        assert comparison.weight_delta_kg is None

    def test_mismatched_poses_are_flagged(self) -> None:
        """Comparing a front shot to a back shot tells the user nothing."""
        comparison = PhotoComparison(
            earlier=self.make(START, "80", PhotoPose.FRONT),
            later=self.make(START + timedelta(days=30), "78", PhotoPose.BACK),
        )
        assert not comparison.poses_match
