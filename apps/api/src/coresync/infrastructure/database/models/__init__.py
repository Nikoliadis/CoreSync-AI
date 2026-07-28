"""ORM model registry.

Importing every model here means ``Base.metadata`` is complete by the time Alembic
autogenerates — a model that is only imported by the code path using it would be
silently missing from migrations.
"""

from coresync.infrastructure.database.base import Base
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

__all__ = [
    "AuthIdentityModel",
    "Base",
    "GoalModel",
    "NutritionTargetModel",
    "ProfileModel",
    "RefreshTokenModel",
    "SingleUseTokenModel",
    "UserDeviceModel",
    "UserModel",
    "UserSettingsModel",
    "WeightLogModel",
]
