"""Progress analytics.

Pure functions over logs. The one idea running through all of it: a lifter's raw daily
weight is mostly water and glycogen, so almost every number worth showing is a *trend*
rather than a reading. Presenting the raw number as progress is how apps convince people
they gained 2 kg overnight.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from coresync.domain.progress.entities import WeightLog

_ZERO = Decimal("0")


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class TrendPoint:
    local_date: date
    weight_kg: Decimal
    trend_kg: Decimal


@dataclass(frozen=True, slots=True)
class WeightTrend:
    """A chart-ready series plus the summary the dashboard tile shows."""

    points: list[TrendPoint]
    start_trend_kg: Decimal | None
    latest_trend_kg: Decimal | None
    latest_weight_kg: Decimal | None
    change_kg: Decimal | None
    weekly_rate_kg: Decimal | None

    @property
    def has_data(self) -> bool:
        return bool(self.points)


class WeightTrendCalculator:
    """EWMA smoothing over a weigh-in series.

    ``SMOOTHING`` of 0.1 gives roughly a ten-day half-life: enough to hide day-to-day
    water swings, not so much that a genuine change takes a month to appear. It is a
    documented, reviewable choice rather than a tuned magic number.
    """

    SMOOTHING = Decimal("0.1")
    # Below this many days apart, a "weekly rate" is extrapolated from noise.
    MIN_DAYS_FOR_RATE = 7

    def __init__(self, smoothing: Decimal | None = None) -> None:
        self._smoothing = smoothing if smoothing is not None else self.SMOOTHING

    def recalculate(self, logs: Sequence[WeightLog]) -> list[WeightLog]:
        """Rewrite the trend column across a whole series, oldest first.

        Called after any insert, edit or delete rather than only on append: a backfilled
        weigh-in from last Tuesday changes every trend value after it, and leaving those
        stale would bend the chart.
        """
        ordered = sorted(logs, key=lambda log: log.local_date)
        previous: Decimal | None = None
        for log in ordered:
            log.apply_trend(previous, self._smoothing)
            previous = log.trend_weight_kg
        return ordered

    def build(self, logs: Sequence[WeightLog]) -> WeightTrend:
        ordered = self.recalculate(logs)
        if not ordered:
            return WeightTrend([], None, None, None, None, None)

        points = [
            TrendPoint(
                local_date=log.local_date,
                weight_kg=log.weight_kg,
                trend_kg=_round(log.trend_weight_kg or log.weight_kg),
            )
            for log in ordered
        ]
        first, last = points[0], points[-1]
        change = _round(last.trend_kg - first.trend_kg)
        return WeightTrend(
            points=points,
            start_trend_kg=first.trend_kg,
            latest_trend_kg=last.trend_kg,
            latest_weight_kg=last.weight_kg,
            change_kg=change,
            weekly_rate_kg=self.weekly_rate(points),
        )

    def weekly_rate(self, points: Sequence[TrendPoint]) -> Decimal | None:
        """Change in trend per week over the window.

        Computed from the trend rather than from first and last raw weights, so a single
        dehydrated morning at either end cannot invent a kilo of progress.
        """
        if len(points) < 2:
            return None
        span_days = (points[-1].local_date - points[0].local_date).days
        if span_days < self.MIN_DAYS_FOR_RATE:
            return None
        delta = points[-1].trend_kg - points[0].trend_kg
        return _round(delta / Decimal(span_days) * 7, "0.001")


@dataclass(frozen=True, slots=True)
class SiteTrend:
    site: str
    first_value: Decimal
    latest_value: Decimal
    change_cm: Decimal
    points: list[tuple[date, Decimal]]


class MeasurementTrendCalculator:
    """Per-site change over a window. No smoothing — measurements are sparse.

    A tape measure is taken weekly at best, so there is nothing to smooth; the honest
    presentation is the readings themselves plus the net change.
    """

    def build(self, series: dict[str, list[tuple[date, Decimal]]]) -> list[SiteTrend]:
        trends: list[SiteTrend] = []
        for site, raw in series.items():
            points = sorted(raw, key=lambda item: item[0])
            if not points:
                continue
            first, latest = points[0][1], points[-1][1]
            trends.append(
                SiteTrend(
                    site=site,
                    first_value=first,
                    latest_value=latest,
                    change_cm=_round(latest - first),
                    points=points,
                )
            )
        return sorted(trends, key=lambda trend: trend.site)


@dataclass(frozen=True, slots=True)
class GoalProjection:
    """When the current trend reaches the target, if it ever does."""

    target_weight_kg: Decimal
    weekly_rate_kg: Decimal
    weeks_remaining: Decimal | None
    projected_date: date | None
    is_moving_away: bool


class GoalProjector:
    """Projects a target date from the observed trend, not from the user's intention.

    Refuses to project when the rate points the wrong way. A cheerful date computed from
    a trend heading away from the goal is worse than no date at all.
    """

    MAX_PROJECTION_WEEKS = Decimal("260")  # five years; beyond that it is meaningless

    def project(
        self,
        *,
        current_trend_kg: Decimal,
        target_weight_kg: Decimal,
        weekly_rate_kg: Decimal,
        today: date,
    ) -> GoalProjection | None:
        remaining = target_weight_kg - current_trend_kg
        if remaining == _ZERO:
            return GoalProjection(target_weight_kg, weekly_rate_kg, _ZERO, today, False)
        if weekly_rate_kg == _ZERO:
            return None

        # Same sign means the trend is closing the gap.
        closing = (remaining > _ZERO) == (weekly_rate_kg > _ZERO)
        if not closing:
            return GoalProjection(target_weight_kg, weekly_rate_kg, None, None, True)

        weeks = abs(remaining / weekly_rate_kg)
        if weeks > self.MAX_PROJECTION_WEEKS:
            return GoalProjection(target_weight_kg, weekly_rate_kg, None, None, False)

        return GoalProjection(
            target_weight_kg=target_weight_kg,
            weekly_rate_kg=weekly_rate_kg,
            weeks_remaining=_round(weeks, "0.1"),
            projected_date=today + timedelta(days=int(weeks * 7)),
            is_moving_away=False,
        )
