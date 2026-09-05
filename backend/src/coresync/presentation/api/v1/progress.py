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
from coresync.application.progress.photos import (
    ComparePhotosUseCase,
    DeletePhotoUseCase,
    FinalizePhotoUseCase,
    ListPhotosUseCase,
    PhotoListQuery,
    RequestPhotoUploadUseCase,
    RequestUploadCommand,
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
    PhotoComparisonResponse,
    PhotoResponse,
    SiteTrendResponse,
    StreakResponse,
    UploadIntentRequest,
    UploadIntentResponse,
    WeightLogResponse,
    WeightPointResponse,
    WeightSeriesResponse,
)

router = APIRouter(prefix="/progress", tags=["progress"])


def _weight_series_response(series) -> WeightSeriesResponse:
    return WeightSeriesResponse(
        points=[WeightPointResponse.model_validate(p) for p in series.points],
        latest_weight_kg=series.latest_weight_kg,
        latest_trend_kg=series.latest_trend_kg,
        change_kg=series.change_kg,
        weekly_rate_kg=series.weekly_rate_kg,
        projection=(
            GoalProjectionResponse.model_validate(series.projection) if series.projection else None
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
    return WeightLogResponse.model_validate(logged)


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
    return [MeasurementResponse.model_validate(m) for m in rows]


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
    return MeasurementResponse.model_validate(measurement)


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
    return MeasurementSeriesResponse(
        trends=[SiteTrendResponse.model_validate(t) for t in series.trends]
    )


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
        workout_streak=StreakResponse.model_validate(data.workout_streak),
        this_week=PeriodTotalsResponse.model_validate(data.this_week),
        last_week=PeriodTotalsResponse.model_validate(data.last_week),
        latest_measurement=(
            MeasurementResponse.model_validate(data.latest_measurement)
            if data.latest_measurement
            else None
        ),
        recent_records=[PersonalRecordResponse.model_validate(r) for r in data.recent_records],
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
    return [MuscleVolumeBucketResponse.model_validate(b) for b in buckets]


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
    return [FrequencyBucketResponse.model_validate(b) for b in buckets]


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
    return [PersonalRecordResponse.model_validate(r) for r in records]


# ---------------------------------------------------------------------- photos
#
# Three calls rather than one, and the split is the security design rather than an
# artefact of REST. The API issues a credential, the client writes the bytes straight to
# private storage, and a second call brings the photo through processing. An API that
# accepted the bytes would be an API that held an un-stripped photo in memory.
#
# Every endpoint here answers 503 when no bucket is configured. That is deliberate: it
# says "photos are off in this deployment", which a client can distinguish from "you have
# no photos".


@router.post(
    "/photos/upload-intent",
    response_model=UploadIntentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Reserve a photo and get a write-only upload URL",
    description=(
        "Creates a pending row and returns a credential scoped to exactly one object, "
        "valid for a few minutes. The photo is not readable — and does not appear in the "
        "timeline as an image — until `POST /photos/{id}/complete` has stripped its "
        "metadata."
    ),
)
async def request_photo_upload(
    body: UploadIntentRequest,
    user: deps.CurrentUser,
    settings: deps.SettingsDep,
    use_case: Annotated[RequestPhotoUploadUseCase, Depends(deps.request_photo_upload_use_case)],
) -> UploadIntentResponse:
    intent = await use_case.execute(
        RequestUploadCommand(
            user_id=user.id,
            content_type=body.content_type,
            pose=body.pose,
            local_date=body.local_date,
            note=body.note,
        ),
        ttl_seconds=settings.upload_url_ttl_seconds,
    )
    return UploadIntentResponse.model_validate(intent)


@router.post(
    "/photos/{photo_id}/complete",
    response_model=PhotoResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Strip the metadata and make the photo readable",
    description=(
        "Re-encodes the uploaded image without EXIF, XMP or IPTC, writes a thumbnail, "
        "and marks the photo ready. Idempotent — calling it on a ready photo returns it "
        "unchanged rather than re-encoding. A failure here leaves the photo unreadable, "
        "which is the only acceptable fallback."
    ),
)
async def complete_photo(
    photo_id: UUID,
    user: deps.CurrentUser,
    settings: deps.SettingsDep,
    use_case: Annotated[FinalizePhotoUseCase, Depends(deps.finalize_photo_use_case)],
) -> PhotoResponse:
    photo = await use_case.execute(
        photo_id=photo_id, user_id=user.id, ttl_seconds=settings.read_url_ttl_seconds
    )
    return PhotoResponse.model_validate(photo)


@router.get(
    "/photos",
    response_model=list[PhotoResponse],
    responses={503: {"model": ErrorResponse}},
    summary="The photo timeline",
    description=(
        "Newest first. Read URLs are minted per request and expire in minutes, so a "
        "cached or logged response body stops being useful almost immediately."
    ),
)
async def list_photos(
    user: deps.CurrentUser,
    settings: deps.SettingsDep,
    use_case: Annotated[ListPhotosUseCase, Depends(deps.list_photos_use_case)],
    pose: Annotated[str | None, Query(pattern="front|side|back|custom")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[PhotoResponse]:
    photos = await use_case.execute(
        PhotoListQuery(
            user_id=user.id,
            pose=pose,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        ),
        ttl_seconds=settings.read_url_ttl_seconds,
    )
    return [PhotoResponse.model_validate(p) for p in photos]


@router.get(
    "/photos/compare",
    response_model=PhotoComparisonResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Two photos side by side",
    description=(
        "Always ordered older to newer regardless of the order asked for, so a slider "
        "runs the way time does. `posesMatch` is false when the two are different poses "
        "— comparing a front shot to a back shot tells the user nothing."
    ),
)
async def compare_photos(
    user: deps.CurrentUser,
    settings: deps.SettingsDep,
    use_case: Annotated[ComparePhotosUseCase, Depends(deps.compare_photos_use_case)],
    first: Annotated[UUID, Query()],
    second: Annotated[UUID, Query()],
) -> PhotoComparisonResponse:
    comparison = await use_case.execute(
        user_id=user.id,
        first_id=first,
        second_id=second,
        ttl_seconds=settings.read_url_ttl_seconds,
    )
    return PhotoComparisonResponse.model_validate(comparison)


@router.delete(
    "/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Delete a photo",
    description=(
        "The row is soft-deleted for the audit trail the schema assumes; the image and "
        "its thumbnail are removed from storage outright. 'Delete my photo' has to mean "
        "the file is gone."
    ),
)
async def delete_photo(
    photo_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[DeletePhotoUseCase, Depends(deps.delete_photo_use_case)],
) -> None:
    await use_case.execute(photo_id=photo_id, user_id=user.id)
