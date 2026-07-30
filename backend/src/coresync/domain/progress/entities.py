"""Body-progress entities.

Phase 1 needs only the weight log — target calculation is impossible without a current
bodyweight. Measurements, photos and trend analytics arrive in Phase 4; the table shape
here is already the one specified in docs/03 §8, so that phase adds features rather
than migrating this away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7


class WeightSource(StrEnum):
    MANUAL = "manual"
    HEALTHKIT = "healthkit"
    GOOGLE_FIT = "google_fit"
    SMART_SCALE = "smart_scale"
    ONBOARDING = "onboarding"


class MeasurementContext(StrEnum):
    MORNING_FASTED = "morning_fasted"
    MORNING = "morning"
    EVENING = "evening"
    POST_WORKOUT = "post_workout"
    UNSPECIFIED = "unspecified"


@dataclass(slots=True)
class WeightLog:
    id: UUID
    user_id: UUID
    local_date: date
    weight_kg: Decimal
    body_fat_pct: Decimal | None = None
    measurement_context: MeasurementContext = MeasurementContext.UNSPECIFIED
    # Exponentially weighted moving average. Raw daily weight is mostly water and
    # glycogen; the trend is the number the user and the coach should reason about.
    trend_weight_kg: Decimal | None = None
    source: WeightSource = WeightSource.MANUAL
    note: str | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        weight_kg: Decimal,
        body_fat_pct: Decimal | None = None,
        source: WeightSource = WeightSource.MANUAL,
        context: MeasurementContext = MeasurementContext.UNSPECIFIED,
        note: str | None = None,
    ) -> WeightLog:
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            weight_kg=weight_kg,
            body_fat_pct=body_fat_pct,
            measurement_context=context,
            trend_weight_kg=weight_kg,  # seeded; smoothed on the next entry
            source=source,
            note=note,
        )

    def apply_trend(self, previous_trend: Decimal | None, smoothing: Decimal) -> None:
        """EWMA over the previous trend value.

        A smoothing factor around 0.1 corresponds to roughly a 10-day half-life, which
        is enough to hide day-to-day water swings without lagging a real change.
        """
        if previous_trend is None:
            self.trend_weight_kg = self.weight_kg
        else:
            raw = previous_trend + smoothing * (self.weight_kg - previous_trend)
            # Quantised to the column's scale. Without this the value returned by a write
            # carries more precision than the numeric(6,2) that stores it, so the client
            # sees 80.200 now and 80.20 on the next read — the same weigh-in appearing to
            # change on its own.
            self.trend_weight_kg = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
