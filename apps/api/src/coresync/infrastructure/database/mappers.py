"""Translation between ORM models and domain entities.

Boilerplate, but bought deliberately: it keeps the domain free of SQLAlchemy, lets
entities carry behaviour without lazy-loading surprises, and makes a schema change a
local edit here rather than a change rippling through business rules.
"""

from __future__ import annotations

from coresync.domain.identity.entities import (
    AuthIdentity,
    AuthProvider,
    RefreshToken,
    SingleUseToken,
    TokenPurpose,
    User,
    UserDevice,
    UserRole,
    UserStatus,
)
from coresync.domain.profile.entities import (
    ActivityLevel,
    ExperienceLevel,
    Gender,
    Goal,
    GoalType,
    NutritionTarget,
    Profile,
    TargetSource,
)
from coresync.infrastructure.database.models.identity import (
    AuthIdentityModel,
    RefreshTokenModel,
    SingleUseTokenModel,
    UserDeviceModel,
    UserModel,
)
from coresync.infrastructure.database.models.profile import (
    GoalModel,
    NutritionTargetModel,
    ProfileModel,
)


class UserMapper:
    @staticmethod
    def to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            password_hash=model.password_hash,
            role=UserRole(model.role),
            status=UserStatus(model.status),
            timezone=model.timezone,
            email_verified_at=model.email_verified_at,
            last_login_at=model.last_login_at,
            failed_login_count=model.failed_login_count,
            locked_until=model.locked_until,
            deleted_at=model.deleted_at,
            created_at=model.created_at,
        )

    @staticmethod
    def to_model(entity: User) -> UserModel:
        return UserModel(
            id=entity.id,
            email=entity.email,
            password_hash=entity.password_hash,
            role=entity.role.value,
            status=entity.status.value,
            timezone=entity.timezone,
            email_verified_at=entity.email_verified_at,
            last_login_at=entity.last_login_at,
            failed_login_count=entity.failed_login_count,
            locked_until=entity.locked_until,
            deleted_at=entity.deleted_at,
        )

    @staticmethod
    def apply(entity: User, model: UserModel) -> None:
        """Copy mutable state onto an already-loaded model, for updates."""
        model.email = entity.email
        model.password_hash = entity.password_hash
        model.role = entity.role.value
        model.status = entity.status.value
        model.timezone = entity.timezone
        model.email_verified_at = entity.email_verified_at
        model.last_login_at = entity.last_login_at
        model.failed_login_count = entity.failed_login_count
        model.locked_until = entity.locked_until
        model.deleted_at = entity.deleted_at


class AuthIdentityMapper:
    @staticmethod
    def to_entity(model: AuthIdentityModel) -> AuthIdentity:
        return AuthIdentity(
            id=model.id,
            user_id=model.user_id,
            provider=AuthProvider(model.provider),
            provider_subject=model.provider_subject,
            provider_email=model.provider_email,
            linked_at=model.linked_at,
        )

    @staticmethod
    def to_model(entity: AuthIdentity) -> AuthIdentityModel:
        return AuthIdentityModel(
            id=entity.id,
            user_id=entity.user_id,
            provider=entity.provider.value,
            provider_subject=entity.provider_subject,
            provider_email=entity.provider_email,
            linked_at=entity.linked_at,
        )


class RefreshTokenMapper:
    @staticmethod
    def to_entity(model: RefreshTokenModel) -> RefreshToken:
        return RefreshToken(
            id=model.id,
            user_id=model.user_id,
            token_hash=model.token_hash,
            expires_at=model.expires_at,
            device_id=model.device_id,
            replaced_by=model.replaced_by,
            revoked_at=model.revoked_at,
            revoked_reason=model.revoked_reason,
            created_ip=str(model.created_ip) if model.created_ip else None,
            user_agent=model.user_agent,
            created_at=model.created_at,
        )

    @staticmethod
    def to_model(entity: RefreshToken) -> RefreshTokenModel:
        return RefreshTokenModel(
            id=entity.id,
            user_id=entity.user_id,
            token_hash=entity.token_hash,
            expires_at=entity.expires_at,
            device_id=entity.device_id,
            replaced_by=entity.replaced_by,
            revoked_at=entity.revoked_at,
            revoked_reason=entity.revoked_reason,
            created_ip=entity.created_ip,
            user_agent=entity.user_agent,
        )

    @staticmethod
    def apply(entity: RefreshToken, model: RefreshTokenModel) -> None:
        model.replaced_by = entity.replaced_by
        model.revoked_at = entity.revoked_at
        model.revoked_reason = entity.revoked_reason


class SingleUseTokenMapper:
    @staticmethod
    def to_entity(model: SingleUseTokenModel) -> SingleUseToken:
        return SingleUseToken(
            id=model.id,
            user_id=model.user_id,
            purpose=TokenPurpose(model.purpose),
            token_hash=model.token_hash,
            expires_at=model.expires_at,
            used_at=model.used_at,
            created_at=model.created_at,
        )

    @staticmethod
    def to_model(entity: SingleUseToken) -> SingleUseTokenModel:
        return SingleUseTokenModel(
            id=entity.id,
            user_id=entity.user_id,
            purpose=entity.purpose.value,
            token_hash=entity.token_hash,
            expires_at=entity.expires_at,
            used_at=entity.used_at,
        )


class UserDeviceMapper:
    @staticmethod
    def to_entity(model: UserDeviceModel) -> UserDevice:
        return UserDevice(
            id=model.id,
            user_id=model.user_id,
            platform=model.platform,
            device_name=model.device_name,
            push_token=model.push_token,
            last_seen_at=model.last_seen_at,
        )

    @staticmethod
    def to_model(entity: UserDevice) -> UserDeviceModel:
        return UserDeviceModel(
            id=entity.id,
            user_id=entity.user_id,
            platform=entity.platform,
            device_name=entity.device_name,
            push_token=entity.push_token,
            last_seen_at=entity.last_seen_at,
        )


class ProfileMapper:
    @staticmethod
    def to_entity(model: ProfileModel) -> Profile:
        return Profile(
            user_id=model.user_id,
            display_name=model.display_name,
            date_of_birth=model.date_of_birth,
            gender=Gender(model.gender) if model.gender else None,
            height_cm=model.height_cm,
            activity_level=ActivityLevel(model.activity_level),
            experience_level=ExperienceLevel(model.experience_level),
            avatar_url=model.avatar_url,
            bio=model.bio,
            onboarded_at=model.onboarded_at,
        )

    @staticmethod
    def to_model(entity: Profile) -> ProfileModel:
        return ProfileModel(
            user_id=entity.user_id,
            display_name=entity.display_name,
            date_of_birth=entity.date_of_birth,
            gender=entity.gender.value if entity.gender else None,
            height_cm=entity.height_cm,
            activity_level=entity.activity_level.value,
            experience_level=entity.experience_level.value,
            avatar_url=entity.avatar_url,
            bio=entity.bio,
            onboarded_at=entity.onboarded_at,
        )

    @staticmethod
    def apply(entity: Profile, model: ProfileModel) -> None:
        model.display_name = entity.display_name
        model.date_of_birth = entity.date_of_birth
        model.gender = entity.gender.value if entity.gender else None
        model.height_cm = entity.height_cm
        model.activity_level = entity.activity_level.value
        model.experience_level = entity.experience_level.value
        model.avatar_url = entity.avatar_url
        model.bio = entity.bio
        model.onboarded_at = entity.onboarded_at


class GoalMapper:
    @staticmethod
    def to_entity(model: GoalModel) -> Goal:
        return Goal(
            id=model.id,
            user_id=model.user_id,
            goal_type=GoalType(model.goal_type),
            target_weight_kg=model.target_weight_kg,
            weekly_rate_kg=model.weekly_rate_kg,
            target_date=model.target_date,
            started_on=model.started_on,
            ended_on=model.ended_on,
        )

    @staticmethod
    def to_model(entity: Goal) -> GoalModel:
        return GoalModel(
            id=entity.id,
            user_id=entity.user_id,
            goal_type=entity.goal_type.value,
            target_weight_kg=entity.target_weight_kg,
            weekly_rate_kg=entity.weekly_rate_kg,
            target_date=entity.target_date,
            started_on=entity.started_on,
            ended_on=entity.ended_on,
        )


class NutritionTargetMapper:
    @staticmethod
    def to_entity(model: NutritionTargetModel) -> NutritionTarget:
        return NutritionTarget(
            id=model.id,
            user_id=model.user_id,
            effective_from=model.effective_from,
            effective_to=model.effective_to,
            calories=model.calories,
            protein_g=model.protein_g,
            carbs_g=model.carbs_g,
            fat_g=model.fat_g,
            fiber_g=model.fiber_g,
            water_ml=model.water_ml,
            source=TargetSource(model.source),
            rationale=model.rationale,
        )

    @staticmethod
    def to_model(entity: NutritionTarget) -> NutritionTargetModel:
        return NutritionTargetModel(
            id=entity.id,
            user_id=entity.user_id,
            effective_from=entity.effective_from,
            effective_to=entity.effective_to,
            calories=entity.calories,
            protein_g=entity.protein_g,
            carbs_g=entity.carbs_g,
            fat_g=entity.fat_g,
            fiber_g=entity.fiber_g,
            water_ml=entity.water_ml,
            source=entity.source.value,
            rationale=entity.rationale,
        )
