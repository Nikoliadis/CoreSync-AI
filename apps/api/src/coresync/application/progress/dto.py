"""Progress DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from coresync.application.catalog.dto import PersonalRecordDTO


# ---------------------------------------------------------------------- weight
@dataclass(frozen=True, slots=True)
class WeightPointDTO:
    local_date: date
    weight_kg: Decimal
    trend_kg: Decimal


@dataclass(frozen=True, slots=True)
class WeightLogDTO:
    id: UUID
    local_date: date
    weight_kg: Decimal
    trend_weight_kg: Decimal | None
    body_fat_pct: Decimal | None
    measurement_context: str
    source: str
    note: str | None


@dataclass(frozen=True, slots=True)
class GoalProjectionDTO:
    target_weight_kg: Decimal
    weekly_rate_kg: Decimal
    weeks_remaining: Decimal | None
    projected_date: date | None
    is_moving_away: bool


@dataclass(frozen=True, slots=True)
class WeightSeriesDTO:
    """Raw dots plus the trend line — both, because either alone misleads.

    The raw series without a trend makes water weight look like progress; the trend
    without the raw points hides how noisy the underlying data is.
    """

    points: list[WeightPointDTO]
    latest_weight_kg: Decimal | None
    latest_trend_kg: Decimal | None
    change_kg: Decimal | None
    weekly_rate_kg: Decimal | None
    projection: GoalProjectionDTO | None = None


# ----------------------------------------------------------------- measurements
@dataclass(frozen=True, slots=True)
class MeasurementDTO:
    id: UUID
    local_date: date
    sites: dict[str, Decimal]
    note: str | None
    waist_to_hip_ratio: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SiteTrendDTO:
    site: str
    first_value_cm: Decimal
    latest_value_cm: Decimal
    change_cm: Decimal
    points: list[tuple[date, Decimal]]


@dataclass(frozen=True, slots=True)
class MeasurementSeriesDTO:
    trends: list[SiteTrendDTO]


# ------------------------------------------------------------------ statistics
@dataclass(frozen=True, slots=True)
class MuscleVolumeBucketDTO:
    """One chart bucket: a period, and the tonnage per muscle group within it."""

    period_start: date
    period_end: date
    volume_by_muscle_group: dict[str, Decimal]
    total_volume_kg: Decimal
    total_sets: int


@dataclass(frozen=True, slots=True)
class FrequencyBucketDTO:
    period_start: date
    period_end: date
    workout_count: int
    total_volume_kg: Decimal
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class StreakDTO:
    current: int
    longest: int
    last_date: date | None


@dataclass(frozen=True, slots=True)
class PeriodTotalsDTO:
    workout_count: int
    total_volume_kg: Decimal
    total_sets: int
    duration_seconds: int
    pr_count: int


@dataclass(frozen=True, slots=True)
class DashboardDTO:
    """The one call the dashboard makes on open.

    Bundled rather than five round-trips because every tile on the screen is useless on
    its own, and a dashboard that paints in five stages looks broken.

    ``nutrition`` is absent until the nutrition domain exists — reported as null rather
    than as zeroes, so the client shows "not tracked" instead of "you ate nothing".
    """

    today: date
    weight: WeightSeriesDTO
    workout_streak: StreakDTO
    this_week: PeriodTotalsDTO
    last_week: PeriodTotalsDTO
    latest_measurement: MeasurementDTO | None
    recent_records: list[PersonalRecordDTO] = field(default_factory=list)
    nutrition: None = None
