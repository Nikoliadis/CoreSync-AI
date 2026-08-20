"""Nutrition use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from coresync.application.common.unit_of_work import UnitOfWork
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    FoodServing,
    FoodSource,
    Macros,
    MealType,
    WaterLog,
)
from coresync.domain.nutrition.services import DayTotals, check_energy, summarise_day

MAX_SEARCH_LIMIT = 50
RECENT_LIMIT = 20


@dataclass(frozen=True, slots=True)
class LogFoodCommand:
    user_id: UUID
    food_id: UUID
    meal_type: MealType
    quantity: Decimal
    serving_id: UUID | None = None
    local_date: date | None = None


@dataclass(frozen=True, slots=True)
class QuickAddCommand:
    user_id: UUID
    meal_type: MealType
    calories: Decimal
    protein_g: Decimal = Decimal(0)
    carbs_g: Decimal = Decimal(0)
    fat_g: Decimal = Decimal(0)
    label: str = "Quick add"
    local_date: date | None = None


class SearchFoodsUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, user_id: UUID, *, query: str, limit: int = 25, offset: int = 0
    ) -> tuple[list[Food], int]:
        async with self._uow:
            return await self._uow.foods.search(
                query=query,
                user_id=user_id,
                limit=min(limit, MAX_SEARCH_LIMIT),
                offset=max(offset, 0),
            )

    async def recent(self, user_id: UUID) -> list[Food]:
        async with self._uow:
            return await self._uow.foods.recent_for_user(user_id, limit=RECENT_LIMIT)

    async def by_barcode(self, user_id: UUID, barcode: str) -> Food | None:
        async with self._uow:
            return await self._uow.foods.by_barcode(barcode, user_id)


class CreateCustomFoodUseCase:
    """A user's own food.

    The energy check runs here as well as in the database so the user gets an
    explanation they can act on — "these macros imply 640 kcal, not 165" — rather than
    a constraint violation surfacing as a 500.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        user_id: UUID,
        *,
        name: str,
        calories_per_100g: Decimal,
        protein_per_100g: Decimal,
        carbs_per_100g: Decimal,
        fat_per_100g: Decimal,
        is_liquid: bool = False,
        servings: list[tuple[str, Decimal]] | None = None,
    ) -> Food:
        try:
            food = Food.create(
                name=name,
                source=FoodSource.USER,
                calories_per_100g=calories_per_100g,
                protein_per_100g=protein_per_100g,
                carbs_per_100g=carbs_per_100g,
                fat_per_100g=fat_per_100g,
                owner_user_id=user_id,
                is_liquid=is_liquid,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        energy = check_energy(food.per_100g)
        if not energy.is_ok:
            raise ValidationError(
                f"Those macros work out to about {int(energy.implied)} kcal, not "
                f"{int(energy.stated)}. Check the numbers on the label.",
                details=[
                    {
                        "field": "caloriesPer100g",
                        "code": "energy_mismatch",
                        "message": f"Expected roughly {int(energy.implied)} kcal.",
                    }
                ],
            )

        async with self._uow:
            await self._uow.foods.add(food)
            if servings:
                built = [
                    FoodServing.create(
                        food_id=food.id, label=label, grams=grams, is_default=index == 0
                    )
                    for index, (label, grams) in enumerate(servings)
                ]
                await self._uow.foods.add_servings(built)
                food.servings = built
            await self._uow.commit()

        return food


class LogFoodUseCase:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, command: LogFoodCommand) -> DiaryEntry:
        async with self._uow:
            user = await self._uow.users.get_by_id(command.user_id)
            if user is None:
                raise NotFoundError("user", command.user_id)
            on = command.local_date or local_date_for(self._clock.now(), user.timezone)

            food = await self._uow.foods.get(command.food_id, command.user_id)
            if food is None:
                raise NotFoundError("That food does not exist.")

            serving = None
            if command.serving_id is not None:
                serving = next((s for s in food.servings if s.id == command.serving_id), None)
                if serving is None:
                    raise ValidationError("That serving does not belong to this food.")

            try:
                entry = DiaryEntry.for_food(
                    user_id=command.user_id,
                    local_date=on,
                    meal_type=command.meal_type,
                    food=food,
                    quantity=command.quantity,
                    serving=serving,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            await self._uow.diary.add(entry)
            # Popularity feeds search ranking, so logging is what makes the catalogue
            # get better at surfacing what people actually eat.
            await self._uow.foods.increment_usage(food.id)
            await self._uow.commit()

        return entry

    async def quick_add(self, command: QuickAddCommand) -> DiaryEntry:
        async with self._uow:
            user = await self._uow.users.get_by_id(command.user_id)
            if user is None:
                raise NotFoundError("user", command.user_id)
            on = command.local_date or local_date_for(self._clock.now(), user.timezone)

            entry = DiaryEntry.quick_add(
                user_id=command.user_id,
                local_date=on,
                meal_type=command.meal_type,
                macros=Macros(
                    calories=command.calories,
                    protein_g=command.protein_g,
                    carbs_g=command.carbs_g,
                    fat_g=command.fat_g,
                ),
                label=command.label,
            )
            await self._uow.diary.add(entry)
            await self._uow.commit()

        return entry


class GetDiaryUseCase:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self, user_id: UUID, *, on: date | None = None
    ) -> tuple[date, DayTotals, list[DiaryEntry], Macros | None]:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            day = on or local_date_for(self._clock.now(), user.timezone)

            entries = await self._uow.diary.entries_for_day(user_id, day)
            water = await self._uow.water.logs_for_day(user_id, day)

            # The targets that were in force on that day, not today's — they are
            # versioned precisely so history stays answerable (docs/03 §5).
            target_row = await self._uow.targets.get_effective_on(user_id, day)
            targets = (
                Macros(
                    calories=target_row.calories,
                    protein_g=target_row.protein_g,
                    carbs_g=target_row.carbs_g,
                    fat_g=target_row.fat_g,
                )
                if target_row
                else None
            )

        return day, summarise_day(entries, water), entries, targets


class DeleteDiaryEntryUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, entry_id: UUID, user_id: UUID) -> None:
        async with self._uow:
            entry = await self._uow.diary.get(entry_id, user_id)
            if entry is None:
                raise NotFoundError("That diary entry does not exist.")
            await self._uow.diary.delete(entry_id, user_id)
            await self._uow.commit()


class LogWaterUseCase:
    def __init__(self, *, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self, user_id: UUID, *, millilitres: Decimal, on: date | None = None
    ) -> tuple[date, Decimal]:
        """Logs an increment and returns the day it landed on with the running total.

        The date is returned rather than recomputed by the caller: "today" is the
        user's local day, and a caller using the server's clock would put a 01:00
        glass of water in Athens on the wrong date.
        """
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            day = on or local_date_for(self._clock.now(), user.timezone)

            try:
                log = WaterLog.create(user_id=user_id, local_date=day, millilitres=millilitres)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            await self._uow.water.add(log)
            logs = await self._uow.water.logs_for_day(user_id, day)
            await self._uow.commit()

        return day, sum((entry.millilitres for entry in logs), Decimal(0))

    async def total_for_day(self, user_id: UUID, on: date | None = None) -> tuple[date, Decimal]:
        async with self._uow:
            user = await self._uow.users.get_by_id(user_id)
            if user is None:
                raise NotFoundError("user", user_id)
            day = on or local_date_for(self._clock.now(), user.timezone)
            logs = await self._uow.water.logs_for_day(user_id, day)
        return day, sum((entry.millilitres for entry in logs), Decimal(0))
