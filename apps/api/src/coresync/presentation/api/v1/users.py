"""/v1/users — profile, onboarding, goals, targets and account lifecycle."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from coresync.application.profile.use_cases import (
    CompleteOnboardingCommand,
    CompleteOnboardingUseCase,
    GetMeUseCase,
    ListTargetHistoryUseCase,
    RecalculateTargetsUseCase,
    ScheduleAccountDeletionUseCase,
    SetGoalCommand,
    SetGoalUseCase,
    SetTargetsCommand,
    SetTargetsManuallyUseCase,
    UpdateProfileCommand,
    UpdateProfileUseCase,
    UpdateSettingsUseCase,
)
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.users import (
    AccountDeletionResponse,
    GoalResponse,
    MeResponse,
    NutritionTargetResponse,
    OnboardingRequest,
    ProfileResponse,
    SetGoalRequest,
    SetTargetsRequest,
    SettingsResponse,
    TargetCalculationResponse,
    UpdateProfileRequest,
    UpdateSettingsRequest,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current user, profile, goal, targets and settings",
    description="The app-boot call: everything a client needs to render its first screen.",
)
async def get_me(
    user: deps.CurrentUser,
    use_case: Annotated[GetMeUseCase, Depends(deps.get_me_use_case)],
) -> MeResponse:
    me = await use_case.execute(user.id)
    return MeResponse(
        user=me.user,  # type: ignore[arg-type]
        profile=me.profile,  # type: ignore[arg-type]
        goal=me.goal,  # type: ignore[arg-type]
        targets=me.targets,  # type: ignore[arg-type]
        settings=SettingsResponse(**me.settings),  # type: ignore[arg-type]
        entitlements=me.entitlements,
    )


@router.patch("/me", response_model=ProfileResponse, summary="Update profile fields")
async def update_profile(
    body: UpdateProfileRequest,
    user: deps.CurrentUser,
    use_case: Annotated[UpdateProfileUseCase, Depends(deps.update_profile_use_case)],
) -> ProfileResponse:
    profile = await use_case.execute(
        UpdateProfileCommand(
            user_id=user.id,
            display_name=body.display_name,
            date_of_birth=body.date_of_birth,
            gender=body.gender,
            height_cm=body.height_cm,
            activity_level=body.activity_level,
            experience_level=body.experience_level,
            bio=body.bio,
        )
    )
    return ProfileResponse(**vars(profile))


@router.put("/me/settings", response_model=SettingsResponse, summary="Update settings")
async def update_settings(
    body: UpdateSettingsRequest,
    user: deps.CurrentUser,
    use_case: Annotated[UpdateSettingsUseCase, Depends(deps.update_settings_use_case)],
) -> SettingsResponse:
    settings = await use_case.execute(user.id, body.model_dump(exclude_none=True))
    return SettingsResponse(**settings)  # type: ignore[arg-type]


@router.post(
    "/me/onboarding",
    response_model=TargetCalculationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Complete onboarding and calculate targets",
    description=(
        "Writes the profile, the starting weigh-in, the goal and the first nutrition "
        "targets in one transaction. `weeklyRateKg` is clamped server-side to a safe "
        "rate, and the calculated calorie target can never fall below the safety floor."
    ),
)
async def complete_onboarding(
    body: OnboardingRequest,
    user: deps.CurrentUser,
    use_case: Annotated[CompleteOnboardingUseCase, Depends(deps.onboarding_use_case)],
) -> TargetCalculationResponse:
    result = await use_case.execute(
        CompleteOnboardingCommand(
            user_id=user.id,
            date_of_birth=body.date_of_birth,
            gender=body.gender,
            height_cm=body.height_cm,
            weight_kg=body.weight_kg,
            activity_level=body.activity_level,
            experience_level=body.experience_level,
            goal_type=body.goal_type,
            target_weight_kg=body.target_weight_kg,
            weekly_rate_kg=body.weekly_rate_kg,
            unit_system=body.unit_system,
        )
    )
    return TargetCalculationResponse(
        target=NutritionTargetResponse(**vars(result.target)),
        bmr=result.bmr,
        tdee=result.tdee,
        was_clamped_to_floor=result.was_clamped_to_floor,
    )


@router.post("/me/goals", response_model=GoalResponse, summary="Set a new goal")
async def set_goal(
    body: SetGoalRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SetGoalUseCase, Depends(deps.set_goal_use_case)],
) -> GoalResponse:
    goal = await use_case.execute(
        SetGoalCommand(
            user_id=user.id,
            goal_type=body.goal_type,
            target_weight_kg=body.target_weight_kg,
            weekly_rate_kg=body.weekly_rate_kg,
            target_date=body.target_date,
        )
    )
    return GoalResponse(**vars(goal))


@router.post(
    "/me/targets/recalculate",
    response_model=TargetCalculationResponse,
    responses={409: {"model": ErrorResponse}},
    summary="Recalculate targets from current profile, weight and goal",
)
async def recalculate_targets(
    user: deps.CurrentUser,
    use_case: Annotated[RecalculateTargetsUseCase, Depends(deps.recalculate_targets_use_case)],
) -> TargetCalculationResponse:
    result = await use_case.execute(user.id)
    return TargetCalculationResponse(
        target=NutritionTargetResponse(**vars(result.target)),
        bmr=result.bmr,
        tdee=result.tdee,
        was_clamped_to_floor=result.was_clamped_to_floor,
    )


@router.put(
    "/me/targets",
    response_model=NutritionTargetResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Set targets manually",
    description=(
        "Rejected below 1200 kcal. That floor is also a CHECK constraint on the table, "
        "so no code path — including the AI coach — can write an unsafe target."
    ),
)
async def set_targets(
    body: SetTargetsRequest,
    user: deps.CurrentUser,
    use_case: Annotated[SetTargetsManuallyUseCase, Depends(deps.set_targets_use_case)],
) -> NutritionTargetResponse:
    target = await use_case.execute(
        SetTargetsCommand(
            user_id=user.id,
            calories=body.calories,
            protein_g=body.protein_g,
            carbs_g=body.carbs_g,
            fat_g=body.fat_g,
            fiber_g=body.fiber_g,
            water_ml=body.water_ml,
        )
    )
    return NutritionTargetResponse(**vars(target))


@router.get(
    "/me/targets/history",
    response_model=list[NutritionTargetResponse],
    summary="Target history",
    description=(
        "Targets are versioned rather than overwritten, so this is the record of what "
        "applied when — which is what makes historical adherence answerable."
    ),
)
async def target_history(
    user: deps.CurrentUser,
    use_case: Annotated[ListTargetHistoryUseCase, Depends(deps.target_history_use_case)],
) -> list[NutritionTargetResponse]:
    targets = await use_case.execute(user.id)
    return [NutritionTargetResponse(**vars(t)) for t in targets]


@router.delete(
    "/me",
    response_model=AccountDeletionResponse,
    summary="Schedule account deletion",
    description=(
        "Soft-deletes immediately and signs out every session. Data is permanently "
        "erased after a 30-day grace period, during which the deletion can be undone."
    ),
)
async def delete_account(
    user: deps.CurrentUser,
    use_case: Annotated[ScheduleAccountDeletionUseCase, Depends(deps.delete_account_use_case)],
) -> AccountDeletionResponse:
    scheduled_for = await use_case.execute(user.id)
    return AccountDeletionResponse(
        scheduled_for=scheduled_for,
        message=(
            "Your account is scheduled for deletion. Sign in again before "
            f"{scheduled_for.isoformat()} to cancel."
        ),
    )
