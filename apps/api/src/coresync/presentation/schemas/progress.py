"""HTTP schemas for weight, measurements and statistics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from coresync.presentation.schemas.common import ApiModel
from coresync.presentation.schemas.exercises import PersonalRecordResponse

MEASUREMENT_SITES = (
    "neck",
    "chest",
    "waist",
    "hips",
    "left_arm",
    "right_arm",
    "left_thigh",
    "right_thigh",
    "left_calf",
    "right_calf",
)
MEASUREMENT_CONTEXTS = (
    "morning_fasted",
    "morning",
    "evening",
    "post_workout",
    "unspecified",
)


# ---------------------------------------------------------------------- weight
class LogWeightRequest(ApiModel):
    weight_kg: Decimal = Field(ge=20, le=500, decimal_places=2)
    local_date: date | None = Field(
        default=None, description="Defaults to today in the user's timezone."
    )
    body_fat_pct: Decimal | None = Field(default=None, gt=0, lt=75, decimal_places=2)
    measurement_context: str = Field(default="unspecified", pattern="|".join(MEASUREMENT_CONTEXTS))
    source: str = Field(default="manual", pattern="manual|healthkit|google_fit|smart_scale")
    note: str | None = Field(default=None, max_length=500)


class WeightLogResponse(ApiModel):
    id: UUID
    local_date: date
    weight_kg: Decimal
    trend_weight_kg: Decimal | None
    body_fat_pct: Decimal | None
    measurement_context: str
    source: str
    note: str | None


class WeightPointResponse(ApiModel):
    local_date: date
    weight_kg: Decimal
    trend_kg: Decimal


class GoalProjectionResponse(ApiModel):
    target_weight_kg: Decimal
    weekly_rate_kg: Decimal
    weeks_remaining: Decimal | None
    projected_date: date | None
    is_moving_away: bool = Field(
        description="True when the trend is heading away from the target, in which case "
        "no date is projected."
    )


class WeightSeriesResponse(ApiModel):
    """Raw dots and the trend line together — either alone misleads."""

    points: list[WeightPointResponse] = Field(default_factory=list)
    latest_weight_kg: Decimal | None
    latest_trend_kg: Decimal | None
    change_kg: Decimal | None
    weekly_rate_kg: Decimal | None
    projection: GoalProjectionResponse | None = None


# ----------------------------------------------------------------- measurements
class LogMeasurementRequest(ApiModel):
    """Only the sites you send are written; omitted sites keep their previous value."""

    neck: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    chest: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    waist: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    hips: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    left_arm: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    right_arm: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    left_thigh: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    right_thigh: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    left_calf: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    right_calf: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    local_date: date | None = None
    note: str | None = Field(default=None, max_length=500)

    def site_values(self) -> dict[str, Decimal | None]:
        return {site: getattr(self, site) for site in MEASUREMENT_SITES}


class MeasurementResponse(ApiModel):
    id: UUID
    local_date: date
    sites: dict[str, Decimal]
    note: str | None
    waist_to_hip_ratio: Decimal | None = None


class SiteTrendResponse(ApiModel):
    site: str
    first_value_cm: Decimal
    latest_value_cm: Decimal
    change_cm: Decimal
    points: list[tuple[date, Decimal]] = Field(default_factory=list)


class MeasurementSeriesResponse(ApiModel):
    trends: list[SiteTrendResponse] = Field(default_factory=list)


# ------------------------------------------------------------------ statistics
class MuscleVolumeBucketResponse(ApiModel):
    period_start: date
    period_end: date
    volume_by_muscle_group: dict[str, Decimal]
    total_volume_kg: Decimal
    total_sets: int


class FrequencyBucketResponse(ApiModel):
    period_start: date
    period_end: date
    workout_count: int
    total_volume_kg: Decimal
    duration_seconds: int


class StreakResponse(ApiModel):
    current: int
    longest: int
    last_date: date | None


class PeriodTotalsResponse(ApiModel):
    workout_count: int
    total_volume_kg: Decimal
    total_sets: int
    duration_seconds: int
    pr_count: int


class DashboardResponse(ApiModel):
    """One call for the whole dashboard.

    `nutrition` is null until the nutrition domain exists — deliberately null rather than
    zeroes, so a client shows "not tracked" instead of "you ate nothing".
    """

    today: date
    weight: WeightSeriesResponse
    workout_streak: StreakResponse
    this_week: PeriodTotalsResponse
    last_week: PeriodTotalsResponse
    latest_measurement: MeasurementResponse | None = None
    recent_records: list[PersonalRecordResponse] = Field(default_factory=list)
    nutrition: None = None
