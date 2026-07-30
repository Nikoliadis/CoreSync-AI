"""Unit of Work port.

One transaction per use case, and one place to reach repositories. The application
layer depends on this Protocol; ``infrastructure`` supplies the SQLAlchemy version and
tests supply an in-memory one.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from coresync.domain.catalog.repositories import (
    CatalogReferenceRepository,
    ExerciseRepository,
)
from coresync.domain.identity.repositories import (
    AuthIdentityRepository,
    RefreshTokenRepository,
    SingleUseTokenRepository,
    UserDeviceRepository,
    UserRepository,
)
from coresync.domain.profile.repositories import (
    GoalRepository,
    NutritionTargetRepository,
    ProfileRepository,
    UserSettingsRepository,
)
from coresync.domain.progress.repositories import (
    BodyMeasurementRepository,
    ProgressPhotoRepository,
    WeightLogRepository,
)
from coresync.domain.workout.repositories import (
    ActivitySummaryRepository,
    ExerciseStatisticsRepository,
    PersonalRecordRepository,
    RoutineRepository,
    StreakRepository,
    SyncOperationLogRepository,
    WorkoutSessionRepository,
)


class UnitOfWork(Protocol):
    users: UserRepository
    auth_identities: AuthIdentityRepository
    refresh_tokens: RefreshTokenRepository
    single_use_tokens: SingleUseTokenRepository
    devices: UserDeviceRepository
    profiles: ProfileRepository
    goals: GoalRepository
    targets: NutritionTargetRepository
    settings: UserSettingsRepository
    weights: WeightLogRepository
    measurements: BodyMeasurementRepository
    photos: ProgressPhotoRepository
    exercises: ExerciseRepository
    catalog: CatalogReferenceRepository
    routines: RoutineRepository
    sessions: WorkoutSessionRepository
    records: PersonalRecordRepository
    summaries: ActivitySummaryRepository
    exercise_stats: ExerciseStatisticsRepository
    streaks: StreakRepository
    sync_log: SyncOperationLogRepository

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
