"""/v1/progress — weight, measurements and statistics.

Progress photos are specified in docs/04 §2.7 but are not mounted yet: the upload
pipeline has to strip EXIF verifiably before any read URL is issued, and that cannot be
claimed without a storage backend to test against.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from coresync.application.progress.measurements import (
    DeleteMeasurementUseCase,
    GetMeasurementSeriesUseCase,
    ListMeasurementsUseCase,
    LogMeasurementCommand,
    LogMeasurementUseCase,
    MeasurementHistoryQuery,
    MeasurementSeriesQuery,
)
from coresync.application.progress.stats import (
    GetDashboardUseCase,
    GetFrequencyUseCase,
    GetVolumeByMuscleGroupUseCase,
    ListAllRecordsUseCase,
    StatsQuery,
)
from coresync.application.progress.weight import (
    DeleteWeightLogUseCase,
    GetWeightSeriesUseCase,
    LogWeightCommand,
    LogWeightUseCase,
    WeightSeriesQuery,
)
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.exercises import PersonalRecordResponse
from coresync.presentation.schemas.progress import (
    DashboardResponse,
    FrequencyBucketResponse,
    GoalProjectionResponse,
    LogMeasurementRequest,
    LogWeightRequest,
    MeasurementResponse,
    MeasurementSeriesResponse,
    MuscleVolumeBucketResponse,
    PeriodTotalsResponse,
    SiteTrendResponse,
    StreakResponse,
    WeightLogResponse,
    WeightPointResponse,
    WeightSeriesResponse,
)

router = APIRouter(prefix="/progress", tags=["progress"])


def _weight_series_response(series) -> WeightSeriesResponse:
    return WeightSeriesResponse(
        points=[WeightPointResponse(**vars(p)) for p in series.points],
        latest_weight_kg=series.latest_weight_kg,
        latest_trend_kg=series.latest_trend_kg,
        change_kg=series.change_kg,
        weekly_rate_kg=series.weekly_rate_kg,
        projection=(
            GoalProjectionResponse(**vars(series.projection)) if series.projection else None
        ),
    )


# ---------------------------------------------------------------------- weight
@router.get(
    "/weight",
    response_model=WeightSeriesResponse,
    summary="Weight logs with the EWMA trend",
    description=(
        "Returns the raw weigh-ins and the smoothed trend line. The trend is computed "
        "over the user's whole history and then windowed, so it continues from what came "
        "before the requested range rather than restarting at its edge."
    ),
)
async def get_weight(
    user: deps.CurrentUser,
    use_case: Annotated[GetWeightSeriesUseCase, Depends(deps.weight_series_use_case)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> WeightSeriesResponse:
    series = await use_case.execute(
        WeightSeriesQuery(user_id=user.id, date_from=date_from, date_to=date_to)
    )
    return _weight_series_response(series)


@router.post(
    "/weight",
    response_model=WeightLogResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Log a weigh-in",
    description=(
        "Upserts on the date — one weigh-in per day, because multiple daily weights are "
        "noise that corrupts the trend. Re-logging corrects the day."
    ),
)
async def log_weight(
    body: LogWeightRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogWeightUseCase, Depends(deps.log_weight_use_case)],
) -> WeightLogResponse:
    logged = await use_case.execute(
        LogWeightCommand(
            user_id=user.id,
            weight_kg=body.weight_kg,
            local_date=body.local_date,
            body_fat_pct=body.body_fat_pct,
            measurement_context=body.measurement_context,
            source=body.source,
            note=body.note,
        )
    )
    return WeightLogResponse(**vars(logged))


@router.delete(
    "/weight/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a weigh-in",
    description="The trend series is recalculated, since removing a point changes every "
    "trend value after it.",
)
async def delete_weight(
    log_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteWeightLogUseCase, Depends(deps.delete_weight_use_case)],
) -> None:
    await use_case.execute(user.id, log_id)


# ----------------------------------------------------------------- measurements
@router.get(
    "/measurements",
    response_model=list[MeasurementResponse],
    summary="Measurement history",
)
async def list_measurements(
    user: deps.CurrentUser,
    use_case: Annotated[ListMeasurementsUseCase, Depends(deps.list_measurements_use_case)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[MeasurementResponse]:
    rows = await use_case.execute(
        MeasurementHistoryQuery(user_id=user.id, date_from=date_from, date_to=date_to)
    )
    return [MeasurementResponse(**vars(m)) for m in rows]


@router.post(
    "/measurements",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Record measurements",
    description=(
        "One row per day. Only the sites you send are written — omitting a site means "
        "you did not measure it today, not that its value is now unknown."
    ),
)
async def log_measurement(
    body: LogMeasurementRequest,
    user: deps.CurrentUser,
    use_case: Annotated[LogMeasurementUseCase, Depends(deps.log_measurement_use_case)],
) -> MeasurementResponse:
    measurement = await use_case.execute(
        LogMeasurementCommand(
            user_id=user.id,
            sites=body.site_values(),
            local_date=body.local_date,
            note=body.note,
        )
    )
    return MeasurementResponse(**vars(measurement))


@router.get(
    "/measurements/series",
    response_model=MeasurementSeriesResponse,
    summary="Per-site chart series",
    description="Defaults to every site. Days a site was not measured are omitted rather "
    "than interpolated.",
)
async def measurement_series(
    user: deps.CurrentUser,
    use_case: Annotated[GetMeasurementSeriesUseCase, Depends(deps.measurement_series_use_case)],
    site: Annotated[list[str] | None, Query()] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> MeasurementSeriesResponse:
    series = await use_case.execute(
        MeasurementSeriesQuery(
            user_id=user.id,
            sites=tuple(site or ()),
            date_from=date_from,
            date_to=date_to,
        )
    )
    return MeasurementSeriesResponse(trends=[SiteTrendResponse(**vars(t)) for t in series.trends])


@router.delete(
    "/measurements/{measurement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Remove a measurement entry",
)
async def delete_measurement(
    measurement_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeleteMeasurementUseCase, Depends(deps.delete_measurement_use_case)],
) -> None:
    await use_case.execute(user.id, measurement_id)


# ------------------------------------------------------------------ statistics
@router.get(
    "/stats/overview",
    response_model=DashboardResponse,
    summary="The dashboard bundle",
    description=(
        "Everything the dashboard paints on open, in one call. Served from the "
        "incrementally maintained aggregates rather than by scanning training history."
    ),
)
async def dashboard(
    user: deps.CurrentUser,
    use_case: Annotated[GetDashboardUseCase, Depends(deps.dashboard_use_case)],
) -> DashboardResponse:
    data = await use_case.execute(user.id)
    return DashboardResponse(
        today=data.today,
        weight=_weight_series_response(data.weight),
        workout_streak=StreakResponse(**vars(data.workout_streak)),
        this_week=PeriodTotalsResponse(**vars(data.this_week)),
        last_week=PeriodTotalsResponse(**vars(data.last_week)),
        latest_measurement=(
            MeasurementResponse(**vars(data.latest_measurement))
            if data.latest_measurement
            else None
        ),
        recent_records=[PersonalRecordResponse(**vars(r)) for r in data.recent_records],
        nutrition=None,
    )


@router.get(
    "/stats/volume",
    response_model=list[MuscleVolumeBucketResponse],
    summary="Volume by muscle group over time",
    description="Bucketed server-side; a year of daily jsonb splits is a lot to ship to "
    "draw twelve bars.",
)
async def volume_by_muscle_group(
    user: deps.CurrentUser,
    use_case: Annotated[GetVolumeByMuscleGroupUseCase, Depends(deps.volume_stats_use_case)],
    granularity: Annotated[str, Query(pattern="week|month")] = "week",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[MuscleVolumeBucketResponse]:
    buckets = await use_case.execute(
        StatsQuery(
            user_id=user.id,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
        )
    )
    return [MuscleVolumeBucketResponse(**vars(b)) for b in buckets]


@router.get(
    "/stats/frequency",
    response_model=list[FrequencyBucketResponse],
    summary="Workouts per week or month",
)
async def frequency(
    user: deps.CurrentUser,
    use_case: Annotated[GetFrequencyUseCase, Depends(deps.frequency_stats_use_case)],
    granularity: Annotated[str, Query(pattern="week|month")] = "week",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[FrequencyBucketResponse]:
    buckets = await use_case.execute(
        StatsQuery(
            user_id=user.id,
            date_from=date_from,
            date_to=date_to,
            granularity=granularity,
        )
    )
    return [FrequencyBucketResponse(**vars(b)) for b in buckets]


@router.get(
    "/stats/records",
    response_model=list[PersonalRecordResponse],
    summary="Every current personal record",
)
async def all_records(
    user: deps.CurrentUser,
    use_case: Annotated[ListAllRecordsUseCase, Depends(deps.all_records_use_case)],
) -> list[PersonalRecordResponse]:
    records = await use_case.execute(user.id)
    return [PersonalRecordResponse(**vars(r)) for r in records]
