"""Profile, onboarding, goals and nutrition targets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from coresync.application.common.dto import (
    AuthenticatedUser,
    GoalDTO,
    MeDTO,
    NutritionTargetDTO,
    ProfileDTO,
    TargetCalculationDTO,
)
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import ConflictError, NotFoundError, ValidationError
from coresync.core.logging import get_logger
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
from coresync.domain.profile.services import TdeeCalculator
from coresync.domain.progress.entities import WeightLog, WeightSource

logger = get_logger(__name__)


# ---------------------------------------------------------------------- mapping
def _profile_dto(profile: Profile, today: date) -> ProfileDTO:
    return ProfileDTO(
        user_id=profile.user_id,
        display_name=profile.display_name,
        date_of_birth=profile.date_of_birth,
        gender=profile.gender.value if profile.gender else None,
        height_cm=profile.height_cm,
        activity_level=profile.activity_level.value,
        experience_level=profile.experience_level.value,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        age=profile.age_at(today),
        is_onboarded=profile.is_onboarded,
    )


def _target_dto(target: NutritionTarget) -> NutritionTargetDTO:
    return NutritionTargetDTO(
        id=target.id,
        effective_from=target.effective_from,
        effective_to=target.effective_to,
        calories=target.calories,
        protein_g=target.protein_g,
        carbs_g=target.carbs_g,
        fat_g=target.fat_g,
        fiber_g=target.fiber_g,
        water_ml=target.water_ml,
        source=target.source.value,
        rationale=target.rationale,
    )


def _goal_dto(goal: Goal) -> GoalDTO:
    return GoalDTO(
        id=goal.id,
        goal_type=goal.goal_type.value,
        target_weight_kg=goal.target_weight_kg,
        weekly_rate_kg=goal.weekly_rate_kg,
        target_date=goal.target_date,
        started_on=goal.started_on,
        ended_on=goal.ended_on,
    )


# ------------------------------------------------------------------------ read
class GetMeUseCase:
    """The app-boot call: everything a client needs to render its first screen."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, user_id: UUID) -> MeDTO:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)

            today = local_date_for(self._clock.now(), user.timezone)
            profile = await self._uow.profiles.get(user_id)
            goal = await self._uow.goals.get_current(user_id)
            target = await self._uow.targets.get_current(user_id)
            settings = await self._uow.settings.get(user_id) or {}

        return MeDTO(
            user=AuthenticatedUser(
                id=user.id,
                email=user.email,
                role=user.role.value,
                tier="free",  # Phase 8 resolves this from `subscriptions`
                status=user.status.value,
                email_verified=user.is_email_verified,
                timezone=user.timezone,
            ),
            profile=_profile_dto(profile, today) if profile else None,
            goal=_goal_dto(goal) if goal else None,
            targets=_target_dto(target) if target else None,
            settings=settings,
            entitlements=["core"],
        )


# ---------------------------------------------------------------------- profile
@dataclass(frozen=True, slots=True)
class UpdateProfileCommand:
    user_id: UUID
    display_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    height_cm: Decimal | None = None
    activity_level: str | None = None
    experience_level: str | None = None
    bio: str | None = None


class UpdateProfileUseCase:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, cmd: UpdateProfileCommand) -> ProfileDTO:
        async with self._uow:
            profile = await self._uow.profiles.get(cmd.user_id)
            if profile is None:
                raise NotFoundError("profile", cmd.user_id)

            if cmd.display_name is not None:
                profile.display_name = cmd.display_name.strip()
            if cmd.date_of_birth is not None:
                user = await self._uow.users.get_by_id(cmd.user_id)
                today = local_date_for(self._clock.now(), user.timezone if user else "UTC")
                try:
                    profile.set_date_of_birth(cmd.date_of_birth, today=today)
                except ValueError as exc:
                    raise ValidationError(
                        str(exc),
                        details=[{"field": "dateOfBirth", "code": "invalid", "message": str(exc)}],
                    ) from exc
            if cmd.gender is not None:
                profile.gender = Gender(cmd.gender)
            if cmd.height_cm is not None:
                profile.height_cm = cmd.height_cm
            if cmd.activity_level is not None:
                profile.activity_level = ActivityLevel(cmd.activity_level)
            if cmd.experience_level is not None:
                profile.experience_level = ExperienceLevel(cmd.experience_level)
            if cmd.bio is not None:
                profile.bio = cmd.bio or None

            await self._uow.profiles.update(profile)
            user = await self._uow.users.get_by_id(cmd.user_id)
            await self._uow.commit()

        today = local_date_for(self._clock.now(), user.timezone if user else "UTC")
        return _profile_dto(profile, today)


class UpdateSettingsUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID, settings: dict[str, object]) -> dict[str, object]:
        async with self._uow:
            await self._uow.settings.upsert(user_id, settings)
            current = await self._uow.settings.get(user_id) or {}
            await self._uow.commit()
        return current


# ------------------------------------------------------------------- onboarding
@dataclass(frozen=True, slots=True)
class CompleteOnboardingCommand:
    user_id: UUID
    date_of_birth: date
    gender: str
    height_cm: Decimal
    weight_kg: Decimal
    activity_level: str
    experience_level: str
    goal_type: str
    target_weight_kg: Decimal | None = None
    weekly_rate_kg: Decimal | None = None
    unit_system: str = "metric"


class CompleteOnboardingUseCase:
    """Turns the onboarding answers into a profile, a goal, a weigh-in and targets.

    One transaction: a user who ends up with a goal but no targets, or a profile but no
    starting weight, is in a state no screen knows how to render.
    """

    def __init__(self, uow: UnitOfWork, calculator: TdeeCalculator, clock: Clock) -> None:
        self._uow = uow
        self._calculator = calculator
        self._clock = clock

    async def execute(self, cmd: CompleteOnboardingCommand) -> TargetCalculationDTO:
        now = self._clock.now()

        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)
            today = local_date_for(now, user.timezone)

            profile = await self._uow.profiles.get(cmd.user_id)
            if profile is None:
                raise NotFoundError("profile", cmd.user_id)

            try:
                profile.set_date_of_birth(cmd.date_of_birth, today=today)
            except ValueError as exc:
                raise ValidationError(
                    str(exc),
                    details=[{"field": "dateOfBirth", "code": "invalid", "message": str(exc)}],
                ) from exc
            profile.gender = Gender(cmd.gender)
            profile.height_cm = cmd.height_cm
            profile.activity_level = ActivityLevel(cmd.activity_level)
            profile.experience_level = ExperienceLevel(cmd.experience_level)
            profile.complete_onboarding(now)
            await self._uow.profiles.update(profile)

            if cmd.unit_system != "metric":
                await self._uow.settings.upsert(cmd.user_id, {"unit_system": cmd.unit_system})

            existing_weight = await self._uow.weights.get_for_date(cmd.user_id, today)
            if existing_weight is None:
                await self._uow.weights.add(
                    WeightLog.create(
                        user_id=cmd.user_id,
                        local_date=today,
                        weight_kg=cmd.weight_kg,
                        source=WeightSource.ONBOARDING,
                    )
                )

            goal_type = GoalType(cmd.goal_type)
            weekly_rate = cmd.weekly_rate_kg
            if weekly_rate is not None:
                # A request for 2 kg/week is common and is not something we help with.
                weekly_rate = self._calculator.clamp_weekly_rate(
                    weekly_rate_kg=weekly_rate, weight_kg=cmd.weight_kg, goal_type=goal_type
                )

            current_goal = await self._uow.goals.get_current(cmd.user_id)
            if current_goal is not None:
                current_goal.close(today)
                await self._uow.goals.update(current_goal)

            goal = Goal.create(
                user_id=cmd.user_id,
                goal_type=goal_type,
                target_weight_kg=cmd.target_weight_kg,
                weekly_rate_kg=weekly_rate,
                target_date=None,
                on=today,
            )
            await self._uow.goals.add(goal)

            calculation = self._calculator.calculate(
                profile=profile, weight_kg=cmd.weight_kg, goal=goal, on=today
            )
            target = await self._replace_current_target(
                user_id=cmd.user_id,
                today=today,
                calories=calculation.calories,
                protein_g=calculation.protein_g,
                carbs_g=calculation.carbs_g,
                fat_g=calculation.fat_g,
                fiber_g=calculation.fiber_g,
                water_ml=calculation.water_ml,
                source=TargetSource.AUTO,
                rationale="Calculated at onboarding from your profile and goal.",
            )
            await self._uow.commit()

        logger.info("onboarding_completed", user_id=str(cmd.user_id))
        return TargetCalculationDTO(
            target=_target_dto(target),
            bmr=calculation.bmr,
            tdee=calculation.tdee,
            was_clamped_to_floor=calculation.was_clamped_to_floor,
        )

    async def _replace_current_target(
        self,
        *,
        user_id: UUID,
        today: date,
        calories: Decimal,
        protein_g: Decimal,
        carbs_g: Decimal,
        fat_g: Decimal,
        fiber_g: Decimal | None,
        water_ml: Decimal,
        source: TargetSource,
        rationale: str | None,
    ) -> NutritionTarget:
        """Close the open target row and open a new one.

        Never an UPDATE in place: the history is what lets the coach answer "was I
        actually in a deficit in March?" (docs/03 §4).
        """
        # Quantised to the column scales before storing. The response to a write is built
        # from this in-memory entity while every later read comes back through the
        # database, so without this the same target reads as "2340" now and "2340.00"
        # after a refresh — a number that appears to change on its own.
        calories = calories.quantize(Decimal("0.01"))
        protein_g = protein_g.quantize(Decimal("0.001"))
        carbs_g = carbs_g.quantize(Decimal("0.001"))
        fat_g = fat_g.quantize(Decimal("0.001"))
        fiber_g = fiber_g.quantize(Decimal("0.001")) if fiber_g is not None else None
        water_ml = water_ml.quantize(Decimal("0.01"))
        current = await self._uow.targets.get_current(user_id)
        if current is not None:
            if current.effective_from == today:
                # Two changes on the same day would produce a zero-length row, which the
                # partial unique index treats as a second "current" target.
                current.calories = calories
                current.protein_g = protein_g
                current.carbs_g = carbs_g
                current.fat_g = fat_g
                current.fiber_g = fiber_g
                current.water_ml = water_ml
                current.source = source
                current.rationale = rationale
                await self._uow.targets.update(current)
                return current
            current.close(today)
            await self._uow.targets.update(current)

        target = NutritionTarget.create(
            user_id=user_id,
            effective_from=today,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            fiber_g=fiber_g,
            water_ml=water_ml,
            source=source,
            rationale=rationale,
        )
        await self._uow.targets.add(target)
        return target


# ------------------------------------------------------------------------ goals
@dataclass(frozen=True, slots=True)
class SetGoalCommand:
    user_id: UUID
    goal_type: str
    target_weight_kg: Decimal | None = None
    weekly_rate_kg: Decimal | None = None
    target_date: date | None = None
    recalculate_targets: bool = True


class SetGoalUseCase:
    def __init__(self, uow: UnitOfWork, calculator: TdeeCalculator, clock: Clock) -> None:
        self._uow = uow
        self._calculator = calculator
        self._clock = clock
        self._onboarding = None  # composed lazily; see _replace_current_target reuse

    async def execute(self, cmd: SetGoalCommand) -> GoalDTO:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)
            today = local_date_for(now, user.timezone)

            current = await self._uow.goals.get_current(cmd.user_id)
            if current is not None:
                current.close(today)
                await self._uow.goals.update(current)

            latest_weight = await self._uow.weights.get_latest(cmd.user_id)
            goal_type = GoalType(cmd.goal_type)
            weekly_rate = cmd.weekly_rate_kg
            if weekly_rate is not None and latest_weight is not None:
                weekly_rate = self._calculator.clamp_weekly_rate(
                    weekly_rate_kg=weekly_rate,
                    weight_kg=latest_weight.weight_kg,
                    goal_type=goal_type,
                )

            goal = Goal.create(
                user_id=cmd.user_id,
                goal_type=goal_type,
                target_weight_kg=cmd.target_weight_kg,
                weekly_rate_kg=weekly_rate,
                target_date=cmd.target_date,
                on=today,
            )
            await self._uow.goals.add(goal)
            await self._uow.commit()

        return _goal_dto(goal)


# ---------------------------------------------------------------------- targets
class RecalculateTargetsUseCase:
    def __init__(self, uow: UnitOfWork, calculator: TdeeCalculator, clock: Clock) -> None:
        self._uow = uow
        self._calculator = calculator
        self._clock = clock

    async def execute(self, user_id: UUID) -> TargetCalculationDTO:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            today = local_date_for(now, user.timezone)

            profile = await self._uow.profiles.get(user_id)
            if profile is None or not profile.has_metrics_for_calculation():
                raise ConflictError(
                    "Complete your profile (date of birth, height and gender) first."
                )
            goal = await self._uow.goals.get_current(user_id)
            if goal is None:
                raise ConflictError("Set a goal before calculating targets.")
            latest_weight = await self._uow.weights.get_latest(user_id)
            if latest_weight is None:
                raise ConflictError("Log your weight before calculating targets.")

            calculation = self._calculator.calculate(
                profile=profile, weight_kg=latest_weight.weight_kg, goal=goal, on=today
            )
            helper = CompleteOnboardingUseCase(self._uow, self._calculator, self._clock)
            target = await helper._replace_current_target(
                user_id=user_id,
                today=today,
                calories=calculation.calories,
                protein_g=calculation.protein_g,
                carbs_g=calculation.carbs_g,
                fat_g=calculation.fat_g,
                fiber_g=calculation.fiber_g,
                water_ml=calculation.water_ml,
                source=TargetSource.AUTO,
                rationale="Recalculated from your current weight, profile and goal.",
            )
            await self._uow.commit()

        return TargetCalculationDTO(
            target=_target_dto(target),
            bmr=calculation.bmr,
            tdee=calculation.tdee,
            was_clamped_to_floor=calculation.was_clamped_to_floor,
        )


@dataclass(frozen=True, slots=True)
class SetTargetsCommand:
    user_id: UUID
    calories: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    water_ml: Decimal | None = None
    fiber_g: Decimal | None = None


class SetTargetsManuallyUseCase:
    """Let the user override their targets — within limits.

    The floor is enforced here *and* by a CHECK constraint on the table. The service
    check produces a helpful message; the constraint is what makes the guarantee real.
    """

    MIN_CALORIES = Decimal("1200")
    MAX_CALORIES = Decimal("6000")

    def __init__(self, uow: UnitOfWork, calculator: TdeeCalculator, clock: Clock) -> None:
        self._uow = uow
        self._calculator = calculator
        self._clock = clock

    async def execute(self, cmd: SetTargetsCommand) -> NutritionTargetDTO:
        if cmd.calories < self.MIN_CALORIES:
            raise ValidationError(
                f"Daily calories cannot be set below {self.MIN_CALORIES:.0f} kcal.",
                details=[
                    {
                        "field": "calories",
                        "code": "below_safety_floor",
                        "message": "This is below a safe intake. Speak to a qualified "
                        "professional if you believe you need less.",
                    }
                ],
            )
        if cmd.calories > self.MAX_CALORIES:
            raise ValidationError("That calorie target is implausibly high.")

        macro_energy = cmd.protein_g * 4 + cmd.carbs_g * 4 + cmd.fat_g * 9
        if abs(macro_energy - cmd.calories) > max(Decimal(100), cmd.calories * Decimal("0.15")):
            raise ValidationError(
                "Your macros do not add up to your calorie target.",
                details=[
                    {
                        "field": "macros",
                        "code": "inconsistent",
                        "message": f"Macros total {macro_energy:.0f} kcal "
                        f"against a target of {cmd.calories:.0f} kcal.",
                    }
                ],
            )

        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(cmd.user_id)
            if user is None:
                raise NotFoundError("user", cmd.user_id)
            today = local_date_for(now, user.timezone)

            latest_weight = await self._uow.weights.get_latest(cmd.user_id)
            water = cmd.water_ml or (
                latest_weight.weight_kg * Decimal("35") if latest_weight else Decimal("2500")
            )

            helper = CompleteOnboardingUseCase(self._uow, self._calculator, self._clock)
            target = await helper._replace_current_target(
                user_id=cmd.user_id,
                today=today,
                calories=cmd.calories,
                protein_g=cmd.protein_g,
                carbs_g=cmd.carbs_g,
                fat_g=cmd.fat_g,
                fiber_g=cmd.fiber_g,
                water_ml=min(max(water, Decimal("1000")), Decimal("6000")),
                source=TargetSource.MANUAL,
                rationale="Set manually.",
            )
            await self._uow.commit()

        return _target_dto(target)


class ListTargetHistoryUseCase:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: UUID) -> list[NutritionTargetDTO]:
        async with self._uow:
            targets = await self._uow.targets.list_for_user(user_id)
        return [_target_dto(t) for t in targets]


# ------------------------------------------------------------- account lifecycle
class ScheduleAccountDeletionUseCase:
    """Soft-delete with a 30-day grace period.

    Hard erasure — including blobs and derived data — runs as a separate scheduled job
    (docs/11 §8). This use case only starts the clock, and the user is told they can
    change their mind.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, user_id: UUID) -> date:
        now = self._clock.now()
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            user.schedule_deletion(now)
            await self._uow.users.update(user)
            await self._uow.refresh_tokens.revoke_all_for_user(user_id, now, "account_deleted")
            await self._uow.commit()

        logger.info("account_deletion_scheduled", user_id=str(user_id))
        from datetime import timedelta

        return (now + timedelta(days=30)).date()
