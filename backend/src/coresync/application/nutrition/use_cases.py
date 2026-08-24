"""Nutrition use cases."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import UUID

from coresync.application.common.ports import ExternalFoodLookup
from coresync.application.common.unit_of_work import UnitOfWork
from coresync.application.nutrition.summaries import refresh_day
from coresync.core.clock import Clock, local_date_for
from coresync.core.errors import NotFoundError, ValidationError
from coresync.core.ids import uuid7
from coresync.domain.nutrition.entities import (
    DiaryEntry,
    Food,
    FoodServing,
    FoodSource,
    Macros,
    MealType,
    TrustTier,
    WaterLog,
)
from coresync.domain.nutrition.services import DayTotals, check_energy, summarise_day


@dataclass(frozen=True, slots=True)
class Nutrient:
    """One measured nutrient, with the unit a label would print it in."""

    code: str
    name: str
    unit: str
    amount_per_100g: Decimal


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
    alcohol_g: Decimal = Decimal(0)
    label: str = "Quick add"
    local_date: date | None = None


class SearchFoodsUseCase:
    def __init__(
        self, *, uow: UnitOfWork, external_foods: ExternalFoodLookup | None = None
    ) -> None:
        self._uow = uow
        self._external = external_foods

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

    async def detail(self, user_id: UUID, food_id: UUID) -> tuple[Food, list[Nutrient]]:
        """One food and everything known about its nutrition."""
        async with self._uow:
            food = await self._uow.foods.get(food_id, user_id)
            if food is None:
                raise NotFoundError("That food does not exist.")
            rows = await self._uow.foods.nutrients_for(food_id)
        return food, [
            Nutrient(code=code, name=name, unit=unit, amount_per_100g=amount)
            for code, name, unit, amount in rows
        ]

    async def by_barcode(self, user_id: UUID, barcode: str) -> Food | None:
        """Local catalogue first, then the outside world — and cache what comes back.

        Caching on first use is what makes scanning get faster over time: the first
        person to scan a product pays the network round trip, and everyone after them
        reads it from our own table. It also means the catalogue grows along the exact
        contour of what our users actually buy, rather than what a bulk import guessed.
        """
        async with self._uow:
            found = await self._uow.foods.by_barcode(barcode, user_id)
        if found is not None or self._external is None:
            return found

        external = await self._external.by_barcode(barcode)
        if external is None:
            return None

        food = Food.create(
            name=f"{external.brand} {external.name}" if external.brand else external.name,
            source=FoodSource.OFF,
            calories_per_100g=external.calories_per_100g,
            protein_per_100g=external.protein_per_100g,
            carbs_per_100g=external.carbs_per_100g,
            fat_per_100g=external.fat_per_100g,
            alcohol_per_100g=external.alcohol_per_100g,
            is_liquid=external.is_liquid,
        )
        # Community data, so tier 3 and never the verified badge — the same rules the
        # bulk import follows, because it is the same data arriving by a different door.
        food.trust_tier = TrustTier.COMMUNITY
        food.is_verified = False

        if not check_energy(food.per_100g).is_ok:
            # The numbers do not reconcile, so we decline to store them at all. A scan
            # that finds nothing is a small disappointment; one that silently records
            # the wrong calories is the failure this phase is built to prevent.
            return None

        async with self._uow:
            # Re-check inside the write transaction: two people can scan the same new
            # product at once, and the second must reuse the first's row.
            existing = await self._uow.foods.by_barcode(barcode, user_id)
            if existing is not None:
                return existing

            await self._uow.foods.add(food)
            await self._uow.foods.add_barcode(food.id, barcode)
            if external.serving_grams:
                serving = FoodServing.create(
                    food_id=food.id,
                    label="1 serving",
                    grams=external.serving_grams,
                    is_default=True,
                )
                await self._uow.foods.add_servings([serving])
                food.servings = [serving]
            await self._uow.commit()

        return food


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
        alcohol_per_100g: Decimal = Decimal(0),
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
                alcohol_per_100g=alcohol_per_100g,
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


class EditCustomFoodUseCase:
    """Correct one of your own foods.

    Only your own: a curated row is shared by everyone, so editing it from the API would
    let one user rewrite what the rest of the app reports. Diary entries already logged
    against this food keep their snapshots and are untouched — that is the point of the
    snapshot.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        food_id: UUID,
        user_id: UUID,
        *,
        name: str,
        calories_per_100g: Decimal,
        protein_per_100g: Decimal,
        carbs_per_100g: Decimal,
        fat_per_100g: Decimal,
        alcohol_per_100g: Decimal = Decimal(0),
        is_liquid: bool = False,
        servings: list[tuple[str, Decimal]] | None = None,
    ) -> Food:
        async with self._uow:
            existing = await self._uow.foods.get(food_id, user_id)
            if existing is None or existing.owner_user_id != user_id:
                raise NotFoundError("That food does not exist.")

            try:
                updated = Food.create(
                    name=name,
                    source=FoodSource.USER,
                    calories_per_100g=calories_per_100g,
                    protein_per_100g=protein_per_100g,
                    carbs_per_100g=carbs_per_100g,
                    fat_per_100g=fat_per_100g,
                    alcohol_per_100g=alcohol_per_100g,
                    owner_user_id=user_id,
                    is_liquid=is_liquid,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

            energy = check_energy(updated.per_100g)
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

            # `Food.create` mints a new id; the row keeps the one it already has.
            updated.id = existing.id
            await self._uow.foods.update(updated)

            if servings is not None:
                built = [
                    FoodServing.create(
                        food_id=updated.id, label=label, grams=grams, is_default=index == 0
                    )
                    for index, (label, grams) in enumerate(servings)
                ]
                await self._uow.foods.replace_servings(updated.id, built)
                updated.servings = built
            else:
                updated.servings = existing.servings

            await self._uow.commit()

        return updated


class DeleteCustomFoodUseCase:
    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, food_id: UUID, user_id: UUID) -> None:
        async with self._uow:
            existing = await self._uow.foods.get(food_id, user_id)
            if existing is None or existing.owner_user_id != user_id:
                raise NotFoundError("That food does not exist.")
            # Soft delete: entries logged against it keep their snapshot, and the row
            # stays so a recipe referencing it does not lose an ingredient.
            await self._uow.foods.delete(food_id, user_id)
            await self._uow.commit()


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
            await refresh_day(self._uow, command.user_id, on)
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
                    alcohol_g=command.alcohol_g,
                ),
                label=command.label,
            )
            await self._uow.diary.add(entry)
            await refresh_day(self._uow, command.user_id, on)
            await self._uow.commit()

        return entry


class EditDiaryEntryUseCase:
    """Change the amount, the meal, or the day of something already logged.

    Re-derived from the food rather than scaled from the stored macros: scaling would
    compound the rounding already applied at log time, so correcting 2000 g to 200 g ten
    times would drift. A quick-add has no food behind it, so its macros are edited
    directly instead.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        entry_id: UUID,
        user_id: UUID,
        *,
        quantity: Decimal | None = None,
        meal_type: MealType | None = None,
        serving_id: UUID | None = None,
        local_date: date | None = None,
    ) -> DiaryEntry:
        async with self._uow:
            entry = await self._uow.diary.get(entry_id, user_id)
            if entry is None:
                raise NotFoundError("That diary entry does not exist.")
            original_date = entry.local_date

            if meal_type is not None:
                entry.meal_type = meal_type
            if local_date is not None:
                entry.local_date = local_date

            if quantity is not None or serving_id is not None:
                if quantity is not None and quantity <= Decimal(0):
                    raise ValidationError("Log an amount greater than zero.")
                await self._rescale(entry, user_id, quantity, serving_id)

            await self._uow.diary.update(entry)
            # Both days: moving an entry changes the total it left as well as the one it
            # joined, and refreshing only the destination would strand the source.
            for day in {original_date, entry.local_date}:
                await refresh_day(self._uow, user_id, day)
            await self._uow.commit()

        return entry

    async def _rescale(
        self,
        entry: DiaryEntry,
        user_id: UUID,
        quantity: Decimal | None,
        serving_id: UUID | None,
    ) -> None:
        amount = quantity if quantity is not None else entry.quantity

        if entry.food_id is None:
            # Quick-add or a recipe entry: there is nothing to re-derive from, so the
            # existing macros are scaled by the change in quantity instead.
            if entry.quantity > Decimal(0):
                factor = amount / entry.quantity
                entry.macros = entry.macros.scaled(factor).rounded()
                entry.total_grams = entry.total_grams * factor
            entry.quantity = amount
            return

        food = await self._uow.foods.get(entry.food_id, user_id)
        if food is None:
            raise ValidationError("That food is no longer available.")

        chosen = serving_id if serving_id is not None else entry.serving_id
        serving = next((s for s in food.servings if s.id == chosen), None)
        if chosen is not None and serving is None:
            raise ValidationError("That serving does not belong to this food.")

        rebuilt = DiaryEntry.for_food(
            user_id=user_id,
            local_date=entry.local_date,
            meal_type=entry.meal_type,
            food=food,
            quantity=amount,
            serving=serving,
        )
        entry.quantity = rebuilt.quantity
        entry.total_grams = rebuilt.total_grams
        entry.macros = rebuilt.macros
        entry.serving_id = rebuilt.serving_id


class CopyDayUseCase:
    """Copy a day's entries, or one meal of it, onto another day.

    Snapshots are copied verbatim rather than re-derived. What was eaten on Tuesday is a
    fact about Tuesday; re-deriving it from today's food data would make a "copy" quietly
    disagree with the thing it copied.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        user_id: UUID,
        *,
        source: date,
        target: date,
        meal_type: MealType | None = None,
    ) -> list[DiaryEntry]:
        if source == target and meal_type is None:
            raise ValidationError("Pick a different day to copy to.")

        async with self._uow:
            entries = await self._uow.diary.entries_for_day(user_id, source)
            if meal_type is not None:
                entries = [e for e in entries if e.meal_type == meal_type]
            if not entries:
                raise ValidationError("There is nothing logged on that day to copy.")

            copies = [
                replace(
                    entry,
                    id=uuid7(),
                    local_date=target,
                    logged_at=None,
                )
                for entry in entries
            ]
            for copy in copies:
                await self._uow.diary.add(copy)
            await refresh_day(self._uow, user_id, target)
            await self._uow.commit()

        return copies


class FavouriteFoodsUseCase:
    """Foods the user has starred.

    Ranked directly below their own foods in search, above trust tier: someone who has
    told us a food matters to them has given a stronger signal than provenance.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        self._uow = uow

    async def list(self, user_id: UUID) -> list[Food]:
        async with self._uow:
            return await self._uow.foods.list_favourites(user_id)

    async def add(self, user_id: UUID, food_id: UUID) -> None:
        async with self._uow:
            food = await self._uow.foods.get(food_id, user_id)
            if food is None:
                raise NotFoundError("That food does not exist.")
            await self._uow.foods.add_favourite(user_id, food_id)
            await self._uow.commit()

    async def remove(self, user_id: UUID, food_id: UUID) -> None:
        async with self._uow:
            await self._uow.foods.remove_favourite(user_id, food_id)
            await self._uow.commit()


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
            await refresh_day(self._uow, user_id, entry.local_date)
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
            await refresh_day(self._uow, user_id, day)
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
