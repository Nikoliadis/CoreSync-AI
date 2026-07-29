"""Translation between ORM models and domain entities.

Boilerplate, but bought deliberately: it keeps the domain free of SQLAlchemy, lets
entities carry behaviour without lazy-loading surprises, and makes a schema change a
local edit here rather than a change rippling through business rules.
"""

from __future__ import annotations

from uuid import UUID

from coresync.domain.catalog.entities import (
    Difficulty,
    Equipment,
    Exercise,
    ExerciseCategory,
    ExerciseMedia,
    ExerciseMuscle,
    ForceType,
    LoggingType,
    Mechanic,
    Muscle,
    MuscleGroup,
    MuscleRole,
)
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
from coresync.domain.workout.entities import (
    PersonalRecord,
    RecordType,
    Routine,
    RoutineExercise,
    RoutineSet,
    SessionExercise,
    SessionSet,
    SessionStatus,
    SetType,
    Visibility,
    WorkoutSession,
)
from coresync.infrastructure.database.models.catalog import (
    EquipmentModel,
    ExerciseCategoryModel,
    ExerciseModel,
    MuscleGroupModel,
    MuscleModel,
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
from coresync.infrastructure.database.models.workout import (
    PersonalRecordModel,
    RoutineExerciseModel,
    RoutineModel,
    RoutineSetModel,
    SessionExerciseModel,
    SessionSetModel,
    WorkoutSessionModel,
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


# ------------------------------------------------------------------- catalog
class MuscleGroupMapper:
    @staticmethod
    def to_entity(model: MuscleGroupModel) -> MuscleGroup:
        return MuscleGroup(
            id=model.id, slug=model.slug, name=model.name, sort_order=model.sort_order
        )


class MuscleMapper:
    @staticmethod
    def to_entity(model: MuscleModel) -> Muscle:
        return Muscle(
            id=model.id,
            slug=model.slug,
            name=model.name,
            muscle_group_id=model.muscle_group_id,
            muscle_group_slug=model.group.slug if model.group else None,
        )


class EquipmentMapper:
    @staticmethod
    def to_entity(model: EquipmentModel) -> Equipment:
        return Equipment(
            id=model.id,
            slug=model.slug,
            name=model.name,
            is_home_available=model.is_home_available,
        )


class ExerciseCategoryMapper:
    @staticmethod
    def to_entity(model: ExerciseCategoryModel) -> ExerciseCategory:
        return ExerciseCategory(
            id=model.id, slug=model.slug, name=model.name, sort_order=model.sort_order
        )


class ExerciseMapper:
    @staticmethod
    def to_entity(model: ExerciseModel, *, is_favorite: bool = False) -> Exercise:
        return Exercise(
            id=model.id,
            slug=model.slug,
            name=model.name,
            category_id=model.category_id,
            logging_type=LoggingType(model.logging_type),
            difficulty=Difficulty(model.difficulty),
            owner_user_id=model.owner_user_id,
            force_type=ForceType(model.force_type) if model.force_type else None,
            mechanic=Mechanic(model.mechanic) if model.mechanic else None,
            is_unilateral=model.is_unilateral,
            is_verified=model.is_verified,
            description=model.description,
            instructions=[i.body for i in model.instructions],
            muscles=[
                ExerciseMuscle(
                    muscle_id=m.muscle_id,
                    role=MuscleRole(m.role),
                    contribution_pct=m.contribution_pct,
                    muscle_slug=m.muscle.slug if m.muscle else None,
                    muscle_name=m.muscle.name if m.muscle else None,
                    muscle_group_slug=(
                        m.muscle.group.slug if m.muscle and m.muscle.group else None
                    ),
                )
                for m in model.muscles
            ],
            equipment_ids=[e.equipment_id for e in model.equipment],
            equipment_slugs=[e.item.slug for e in model.equipment if e.item],
            media=[
                ExerciseMedia(
                    id=media.id,
                    media_type=media.media_type,
                    url=media.url,
                    sort_order=media.sort_order,
                )
                for media in model.media
            ],
            category_slug=model.category.slug if model.category else None,
            is_favorite=is_favorite,
        )

    @staticmethod
    def to_model(entity: Exercise) -> ExerciseModel:
        return ExerciseModel(
            id=entity.id,
            slug=entity.slug,
            name=entity.name,
            category_id=entity.category_id,
            owner_user_id=entity.owner_user_id,
            force_type=entity.force_type.value if entity.force_type else None,
            mechanic=entity.mechanic.value if entity.mechanic else None,
            difficulty=entity.difficulty.value,
            logging_type=entity.logging_type.value,
            is_unilateral=entity.is_unilateral,
            is_verified=entity.is_verified,
            description=entity.description,
        )

    @staticmethod
    def apply(entity: Exercise, model: ExerciseModel) -> None:
        model.name = entity.name
        model.category_id = entity.category_id
        model.force_type = entity.force_type.value if entity.force_type else None
        model.mechanic = entity.mechanic.value if entity.mechanic else None
        model.difficulty = entity.difficulty.value
        model.logging_type = entity.logging_type.value
        model.is_unilateral = entity.is_unilateral
        model.description = entity.description


# ------------------------------------------------------------------ routines
class RoutineSetMapper:
    @staticmethod
    def to_entity(model: RoutineSetModel) -> RoutineSet:
        return RoutineSet(
            id=model.id,
            set_number=model.set_number,
            set_type=SetType(model.set_type),
            target_reps_min=model.target_reps_min,
            target_reps_max=model.target_reps_max,
            target_weight_kg=model.target_weight_kg,
            target_duration_seconds=model.target_duration_seconds,
            target_distance_m=model.target_distance_m,
            target_rpe=model.target_rpe,
        )

    @staticmethod
    def to_model(entity: RoutineSet, routine_exercise_id: UUID) -> RoutineSetModel:
        return RoutineSetModel(
            id=entity.id,
            routine_exercise_id=routine_exercise_id,
            set_number=entity.set_number,
            set_type=entity.set_type.value,
            target_reps_min=entity.target_reps_min,
            target_reps_max=entity.target_reps_max,
            target_weight_kg=entity.target_weight_kg,
            target_duration_seconds=entity.target_duration_seconds,
            target_distance_m=entity.target_distance_m,
            target_rpe=entity.target_rpe,
        )


class RoutineExerciseMapper:
    @staticmethod
    def to_entity(model: RoutineExerciseModel) -> RoutineExercise:
        return RoutineExercise(
            id=model.id,
            exercise_id=model.exercise_id,
            position=model.position,
            superset_group=model.superset_group,
            rest_seconds=model.rest_seconds,
            notes=model.notes,
            sets=[RoutineSetMapper.to_entity(s) for s in model.sets],
        )

    @staticmethod
    def to_model(entity: RoutineExercise, routine_id: UUID) -> RoutineExerciseModel:
        return RoutineExerciseModel(
            id=entity.id,
            routine_id=routine_id,
            exercise_id=entity.exercise_id,
            position=entity.position,
            superset_group=entity.superset_group,
            rest_seconds=entity.rest_seconds,
            notes=entity.notes,
            sets=[RoutineSetMapper.to_model(s, entity.id) for s in entity.sets],
        )


class RoutineMapper:
    @staticmethod
    def to_entity(model: RoutineModel) -> Routine:
        return Routine(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            folder=model.folder,
            notes=model.notes,
            is_template=model.is_template,
            estimated_minutes=model.estimated_minutes,
            position=model.position,
            version=model.version,
            last_performed_at=model.last_performed_at,
            exercises=[RoutineExerciseMapper.to_entity(e) for e in model.exercises],
        )

    @staticmethod
    def to_model(entity: Routine) -> RoutineModel:
        return RoutineModel(
            id=entity.id,
            user_id=entity.user_id,
            name=entity.name,
            folder=entity.folder,
            notes=entity.notes,
            is_template=entity.is_template,
            estimated_minutes=entity.estimated_minutes,
            position=entity.position,
            version=entity.version,
            last_performed_at=entity.last_performed_at,
            exercises=[RoutineExerciseMapper.to_model(e, entity.id) for e in entity.exercises],
        )

    @staticmethod
    def apply(entity: Routine, model: RoutineModel) -> None:
        model.name = entity.name
        model.folder = entity.folder
        model.notes = entity.notes
        model.estimated_minutes = entity.estimated_minutes
        model.position = entity.position
        model.version = entity.version


# ------------------------------------------------------------------ sessions
class SessionSetMapper:
    @staticmethod
    def to_entity(model: SessionSetModel, *, exercise_id: UUID | None = None) -> SessionSet:
        return SessionSet(
            id=model.id,
            session_exercise_id=model.session_exercise_id,
            set_number=model.set_number,
            set_type=SetType(model.set_type),
            reps=model.reps,
            weight_kg=model.weight_kg,
            duration_seconds=model.duration_seconds,
            distance_m=model.distance_m,
            rpe=model.rpe,
            is_completed=model.is_completed,
            completed_at=model.completed_at,
            exercise_id=exercise_id,
        )

    @staticmethod
    def to_model(entity: SessionSet) -> SessionSetModel:
        # `estimated_1rm` is deliberately absent: it is a generated column, so the
        # database is the only writer and the two definitions cannot drift.
        return SessionSetModel(
            id=entity.id,
            session_exercise_id=entity.session_exercise_id,
            set_number=entity.set_number,
            set_type=entity.set_type.value,
            reps=entity.reps,
            weight_kg=entity.weight_kg,
            duration_seconds=entity.duration_seconds,
            distance_m=entity.distance_m,
            rpe=entity.rpe,
            is_completed=entity.is_completed,
            completed_at=entity.completed_at,
        )

    @staticmethod
    def apply(entity: SessionSet, model: SessionSetModel) -> None:
        model.set_number = entity.set_number
        model.set_type = entity.set_type.value
        model.reps = entity.reps
        model.weight_kg = entity.weight_kg
        model.duration_seconds = entity.duration_seconds
        model.distance_m = entity.distance_m
        model.rpe = entity.rpe
        model.is_completed = entity.is_completed
        model.completed_at = entity.completed_at


class SessionExerciseMapper:
    @staticmethod
    def to_entity(model: SessionExerciseModel) -> SessionExercise:
        return SessionExercise(
            id=model.id,
            session_id=model.session_id,
            exercise_id=model.exercise_id,
            position=model.position,
            superset_group=model.superset_group,
            rest_seconds=model.rest_seconds,
            notes=model.notes,
            sets=[SessionSetMapper.to_entity(s, exercise_id=model.exercise_id) for s in model.sets],
        )

    @staticmethod
    def to_model(entity: SessionExercise) -> SessionExerciseModel:
        return SessionExerciseModel(
            id=entity.id,
            session_id=entity.session_id,
            exercise_id=entity.exercise_id,
            position=entity.position,
            superset_group=entity.superset_group,
            rest_seconds=entity.rest_seconds,
            notes=entity.notes,
            sets=[SessionSetMapper.to_model(s) for s in entity.sets],
        )

    @staticmethod
    def apply(entity: SessionExercise, model: SessionExerciseModel) -> None:
        model.position = entity.position
        model.superset_group = entity.superset_group
        model.rest_seconds = entity.rest_seconds
        model.notes = entity.notes


class WorkoutSessionMapper:
    @staticmethod
    def to_entity(model: WorkoutSessionModel) -> WorkoutSession:
        return WorkoutSession(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            started_at=model.started_at,
            local_date=model.local_date,
            routine_id=model.routine_id,
            notes=model.notes,
            completed_at=model.completed_at,
            duration_seconds=model.duration_seconds,
            total_volume_kg=model.total_volume_kg,
            total_sets=model.total_sets,
            total_reps=model.total_reps,
            perceived_effort=model.perceived_effort,
            status=SessionStatus(model.status),
            visibility=Visibility(model.visibility),
            client_session_id=model.client_session_id,
            exercises=[SessionExerciseMapper.to_entity(e) for e in model.exercises],
        )

    @staticmethod
    def to_model(entity: WorkoutSession) -> WorkoutSessionModel:
        return WorkoutSessionModel(
            id=entity.id,
            user_id=entity.user_id,
            routine_id=entity.routine_id,
            name=entity.name,
            notes=entity.notes,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            local_date=entity.local_date,
            duration_seconds=entity.duration_seconds,
            total_volume_kg=entity.total_volume_kg,
            total_sets=entity.total_sets,
            total_reps=entity.total_reps,
            perceived_effort=entity.perceived_effort,
            status=entity.status.value,
            visibility=entity.visibility.value,
            client_session_id=entity.client_session_id,
            exercises=[SessionExerciseMapper.to_model(e) for e in entity.exercises],
        )

    @staticmethod
    def apply(entity: WorkoutSession, model: WorkoutSessionModel) -> None:
        model.name = entity.name
        model.notes = entity.notes
        model.completed_at = entity.completed_at
        model.duration_seconds = entity.duration_seconds
        model.total_volume_kg = entity.total_volume_kg
        model.total_sets = entity.total_sets
        model.total_reps = entity.total_reps
        model.perceived_effort = entity.perceived_effort
        model.status = entity.status.value
        model.visibility = entity.visibility.value


class PersonalRecordMapper:
    @staticmethod
    def to_entity(model: PersonalRecordModel) -> PersonalRecord:
        return PersonalRecord(
            id=model.id,
            user_id=model.user_id,
            exercise_id=model.exercise_id,
            record_type=RecordType(model.record_type),
            value=model.value,
            achieved_on=model.achieved_on,
            reps_at_value=model.reps_at_value,
            session_set_id=model.session_set_id,
            previous_record_id=model.previous_record_id,
            is_current=model.is_current,
        )

    @staticmethod
    def to_model(entity: PersonalRecord) -> PersonalRecordModel:
        return PersonalRecordModel(
            id=entity.id,
            user_id=entity.user_id,
            exercise_id=entity.exercise_id,
            record_type=entity.record_type.value,
            value=entity.value,
            reps_at_value=entity.reps_at_value,
            session_set_id=entity.session_set_id,
            achieved_on=entity.achieved_on,
            previous_record_id=entity.previous_record_id,
            is_current=entity.is_current,
        )
