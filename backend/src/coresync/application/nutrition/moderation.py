"""Submitting a food for the shared catalogue, and reviewing what was submitted.

Food data quality is the fatal risk of this phase: a product that tells someone they ate
300 kcal when they ate 600 is worse than one that tells them nothing. Trust tiers are the
structural half of the mitigation and this queue is the human half — nothing reaches the
shared catalogue without a person having looked at the numbers.

Approval promotes to tier 2, never tier 1. Tier 1 means a curator wrote those numbers;
tier 2 means a reviewer checked somebody else's.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock
from coresync.core.errors import NotFoundError, ValidationError
from coresync.domain.nutrition.entities import (
    Food,
    FoodSubmission,
    SubmissionStatus,
    TrustTier,
)
from coresync.domain.nutrition.services import check_energy

MAX_NOTE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class QueuedSubmission:
    """A queue row with the food attached, so a reviewer sees the numbers not an id."""

    submission: FoodSubmission
    food: Food

    @property
    def energy_is_consistent(self) -> bool:
        """Shown to the reviewer rather than enforced.

        The database already refuses a row whose macros contradict its calories, so
        anything reaching the queue passed that bar. This flags the ones that passed
        only by the width of the tolerance, which is where a reviewer's attention is
        worth most.
        """
        result = check_energy(self.food.per_100g)
        return result.is_ok and result.difference <= result.tolerance / 2


class SubmitFoodUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, food_id: UUID, user_id: UUID, *, note: str | None = None
    ) -> FoodSubmission:
        if note and len(note) > MAX_NOTE_LENGTH:
            raise ValidationError(f"Keep the note under {MAX_NOTE_LENGTH} characters.")

        async with self._uow:
            food = await self._uow.foods.get(food_id, user_id)
            if food is None or food.owner_user_id != user_id:
                raise NotFoundError("That food does not exist.")
            if not food.is_custom:
                raise ValidationError("That food is already in the shared catalogue.")

            existing = await self._uow.food_submissions.pending_for_food(food_id)
            if existing is not None:
                # Not an error: the user asked for a state that already holds.
                return existing

            submission = FoodSubmission.create(food_id=food_id, user_id=user_id, note=note)
            await self._uow.food_submissions.add(submission)
            await self._uow.commit()

        return submission


class ListSubmissionQueueUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, *, status: SubmissionStatus = SubmissionStatus.PENDING, limit: int = 50
    ) -> list[QueuedSubmission]:
        async with self._uow:
            return await self._uow.food_submissions.queue(status=status, limit=limit)


class ReviewSubmissionUseCase:
    """Approve or reject. Both are terminal; a food is resubmitted, not reopened."""

    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def approve(
        self, submission_id: UUID, reviewer_id: UUID, *, note: str | None = None
    ) -> FoodSubmission:
        async with self._uow:
            submission = await self._resolve(submission_id)
            # Read without a user scope: this is the admin path, and the food belongs to
            # somebody else by definition.
            food = await self._uow.food_submissions.food_for(submission.food_id)
            if food is None:
                raise NotFoundError("That food no longer exists.")

            energy = check_energy(food.per_100g)
            if not energy.is_ok:
                # Belt and braces. The database constraint should have stopped this on
                # the way in, and if it somehow did not, publishing it to everyone is
                # the worst possible moment to find out.
                raise ValidationError(
                    f"Those macros imply about {int(energy.implied)} kcal, not "
                    f"{int(energy.stated)}. Fix the food before approving it."
                )

            # Public, and official rather than curated — a reviewer checked these
            # numbers, they did not author them.
            await self._uow.food_submissions.publish(food.id, trust_tier=TrustTier.OFFICIAL)
            return await self._close(submission, reviewer_id, SubmissionStatus.APPROVED, note)

    async def reject(
        self, submission_id: UUID, reviewer_id: UUID, *, note: str | None = None
    ) -> FoodSubmission:
        async with self._uow:
            submission = await self._resolve(submission_id)
            # The food is untouched: it stays private and usable by its owner, who has
            # lost nothing but the promotion.
            return await self._close(submission, reviewer_id, SubmissionStatus.REJECTED, note)

    async def _resolve(self, submission_id: UUID) -> FoodSubmission:
        submission = await self._uow.food_submissions.get(submission_id)
        if submission is None:
            raise NotFoundError("That submission does not exist.")
        if not submission.is_open:
            raise ValidationError("That submission has already been reviewed.")
        return submission

    async def _close(
        self,
        submission: FoodSubmission,
        reviewer_id: UUID,
        status: SubmissionStatus,
        note: str | None,
    ) -> FoodSubmission:
        submission.status = status
        submission.reviewed_by = reviewer_id
        submission.reviewed_at = self._clock.now()
        if note:
            submission.note = note[:MAX_NOTE_LENGTH]
        await self._uow.food_submissions.update(submission)
        await self._uow.commit()
        return submission
