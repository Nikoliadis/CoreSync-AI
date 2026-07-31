"""ORM model registry.

Importing every model here means ``Base.metadata`` is complete by the time Alembic
autogenerates — a model that is only imported by the code path using it would be
silently missing from migrations.
"""

from coresync.infrastructure.database.base import Base
from coresync.infrastructure.database.models.aggregates import (
    DailyActivitySummaryModel,
    ExerciseStatisticsModel,
    UserStreakModel,
)
from coresync.infrastructure.database.models.catalog import (
    EquipmentModel,
    ExerciseCategoryModel,
    ExerciseEquipmentModel,
    ExerciseInstructionModel,
    ExerciseMediaModel,
    ExerciseModel,
    ExerciseMuscleModel,
    MuscleGroupModel,
    MuscleModel,
    UserFavoriteExerciseModel,
)
from coresync.infrastructure.database.models.coaching import (
    AiConversationModel,
    AiEmbeddingModel,
    AiInsightModel,
    AiMessageModel,
    AiToolCallModel,
    AiUsageLogModel,
)
from coresync.infrastructure.database.models.identity import (
    AuthIdentityModel,
    RefreshTokenModel,
    SingleUseTokenModel,
    UserDeviceModel,
    UserModel,
    UserSettingsModel,
)
from coresync.infrastructure.database.models.profile import (
    GoalModel,
    NutritionTargetModel,
    ProfileModel,
)
from coresync.infrastructure.database.models.progress import WeightLogModel
from coresync.infrastructure.database.models.progress_body import (
    BodyMeasurementModel,
    ProgressPhotoModel,
)
from coresync.infrastructure.database.models.workout import (
    PersonalRecordModel,
    RoutineExerciseModel,
    RoutineModel,
    RoutineSetModel,
    SessionExerciseModel,
    SessionSetModel,
    SyncOperationModel,
    WorkoutSessionModel,
)

__all__ = [
    "AiConversationModel",
    "AiEmbeddingModel",
    "AiInsightModel",
    "AiMessageModel",
    "AiToolCallModel",
    "AiUsageLogModel",
    "AuthIdentityModel",
    "Base",
    "BodyMeasurementModel",
    "DailyActivitySummaryModel",
    "EquipmentModel",
    "ExerciseCategoryModel",
    "ExerciseEquipmentModel",
    "ExerciseInstructionModel",
    "ExerciseMediaModel",
    "ExerciseModel",
    "ExerciseMuscleModel",
    "ExerciseStatisticsModel",
    "GoalModel",
    "MuscleGroupModel",
    "MuscleModel",
    "NutritionTargetModel",
    "PersonalRecordModel",
    "ProfileModel",
    "ProgressPhotoModel",
    "RefreshTokenModel",
    "RoutineExerciseModel",
    "RoutineModel",
    "RoutineSetModel",
    "SessionExerciseModel",
    "SessionSetModel",
    "SingleUseTokenModel",
    "SyncOperationModel",
    "UserDeviceModel",
    "UserFavoriteExerciseModel",
    "UserModel",
    "UserSettingsModel",
    "UserStreakModel",
    "WeightLogModel",
    "WorkoutSessionModel",
]
