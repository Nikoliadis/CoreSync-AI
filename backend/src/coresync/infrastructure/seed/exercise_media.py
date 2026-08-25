"""Import demonstration photographs from the Free Exercise DB.

A name and a muscle list tell an experienced lifter what to do and tell a beginner
nothing. Pictures are what make the catalogue usable by someone who has never held a
barbell, and `exercise_media` has existed in the schema since the first migration
without ever holding a row.

**Source and licence.** https://github.com/yuhonas/free-exercise-db — 873 exercises, two
photographs each, released under **The Unlicense**: public domain, commercial use, no
attribution required. That was the deciding factor over the alternatives; wger's images
are CC-BY-SA and carry a share-alike obligation, and the animated-GIF APIs are paid and
generally forbid re-hosting.

**Why matching is deliberately strict.** Their catalogue and ours were written
independently, so 202 of our 274 movements have no identically-named entry. It is
tempting to close that gap with fuzzy matching, and it is a trap: token-similarity
scoring pairs our "Barbell Row" with their "Barbell Rear Delt Row" at *maximum*
confidence, and "Bear Crawl" with "Bear Crawl Sled Drags". Those are different movements.
Showing someone the wrong demonstration for a loaded barbell is worse than showing them
nothing, so this module matches on exact names and a hand-checked alias table, and
reports whatever is left rather than guessing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from coresync.core.config import get_settings
from coresync.core.ids import uuid7
from coresync.core.logging import configure_logging, get_logger
from coresync.infrastructure.database.models.catalog import ExerciseMediaModel, ExerciseModel
from coresync.infrastructure.database.session import Database

logger = get_logger(__name__)

_FETCH_TIMEOUT = 60.0

CATALOGUE_URL = (
    "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
)

#: Where the image paths in the catalogue resolve against.
#:
#: Defaults to the project's own raw content so an import works with no infrastructure at
#: all. Serving a production app straight off raw.githubusercontent is fragile and rude
#: — mirror the files into object storage and pass that origin instead. The content is
#: public domain, so mirroring is explicitly allowed.
DEFAULT_IMAGE_ORIGIN = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises"

#: Our slug to their exact name. Every entry here has been checked by eye against the
#: source catalogue; an entry that no longer resolves is a hard error rather than a
#: silent skip, so their renaming something cannot quietly empty a row.
ALIASES: dict[str, str] = {
    # --- squat
    "back-squat": "Barbell Squat",
    "front-squat": "Front Barbell Squat",
    "high-bar-squat": "Olympic Squat",
    "low-bar-squat": "Barbell Squat",
    "box-jump": "Box Jump (Multiple Response)",
    "jump-squat": "Freehand Jump Squat",
    "bulgarian-split-squat": "One Leg Barbell Squat",
    "kettlebell-goblet-squat": "Goblet Squat",
    "pistol-squat": "Kettlebell Pistol Squat",
    "overhead-press": "Barbell Shoulder Press",
    # --- hinge
    "deadlift": "Barbell Deadlift",
    "stiff-leg-deadlift": "Stiff-Legged Barbell Deadlift",
    "dumbbell-romanian-deadlift": "Romanian Deadlift",
    "snatch-grip-deadlift": "Snatch Deadlift",
    "glute-bridge": "Butt Lift (Bridge)",
    "nordic-curl": "Natural Glute Ham Raise",
    "back-extension": "Hyperextensions (Back Extensions)",
    "weighted-back-extension": "Weighted Ball Hyperextension",
    # --- press
    "barbell-bench-press": "Barbell Bench Press - Medium Grip",
    "incline-barbell-bench-press": "Barbell Incline Bench Press - Medium Grip",
    "decline-dumbbell-press": "Decline Dumbbell Bench Press",
    "close-grip-bench-press": "Close-Grip Barbell Bench Press",
    "seated-dumbbell-press": "Dumbbell Shoulder Press",
    "seated-barbell-press": "Barbell Shoulder Press",
    "arnold-press": "Arnold Dumbbell Press",
    "behind-the-neck-press": "Bradford/Rocky Presses",
    "push-up": "Pushups",
    "diamond-push-up": "Push-Ups - Close Triceps Position",
    "wide-grip-push-up": "Push-Up Wide",
    "clap-push-up": "Plyo Push-up",
    "handstand-push-up": "Handstand Push-Ups",
    # --- pull
    "pull-up": "Pullups",
    "wide-grip-pull-up": "Wide-Grip Rear Pull-Up",
    "neutral-grip-pull-up": "V-Bar Pullup",
    "assisted-pull-up": "Band Assisted Pull-Up",
    "weighted-pull-up": "Weighted Pull Ups",
    "lat-pulldown": "Wide-Grip Lat Pulldown",
    "close-grip-lat-pulldown": "Close-Grip Front Lat Pulldown",
    "reverse-grip-lat-pulldown": "Underhand Cable Pulldowns",
    "barbell-row": "Bent Over Barbell Row",
    "dumbbell-row": "One-Arm Dumbbell Row",
    "chest-supported-dumbbell-row": "Dumbbell Incline Row",
    "seated-cable-row": "Seated Cable Rows",
    "single-arm-cable-row": "Seated One-arm Cable Pulley Rows",
    "t-bar-row": "Lying T-Bar Row",
    "pendlay-row": "Bent Over Barbell Row",
    "yates-row": "Reverse Grip Bent-Over Rows",
    "trx-row": "Inverted Row",
    "machine-row": "Leverage Iso Row",
    "kroc-row": "One-Arm Dumbbell Row",
    "meadows-row": "One-Arm Long Bar Row",
    "rack-pull": "Rack Pulls",
    # --- shoulders
    "lateral-raise": "Side Lateral Raise",
    "front-raise": "Front Dumbbell Raise",
    "plate-front-raise": "Front Plate Raise",
    "cable-front-raise": "Front Cable Raise",
    "rear-delt-fly": "Reverse Flyes",
    "reverse-pec-deck": "Reverse Machine Flyes",
    "upright-row": "Upright Barbell Row",
    "cable-upright-row": "Upright Cable Row",
    "machine-shoulder-press": "Machine Shoulder (Military) Press",
    "external-rotation": "External Rotation with Cable",
    # --- arms
    "dumbbell-curl": "Dumbbell Bicep Curl",
    "alternating-dumbbell-curl": "Dumbbell Alternate Bicep Curl",
    "hammer-curl": "Hammer Curls",
    "cable-hammer-curl": "Cable Hammer Curls - Rope Attachment",
    "cable-curl": "Overhead Cable Curl",
    "concentration-curl": "Concentration Curls",
    "dumbbell-preacher-curl": "One Arm Dumbbell Preacher Curl",
    "machine-curl": "Machine Bicep Curl",
    "reverse-curl": "Reverse Barbell Curl",
    "wrist-curl": "Palms-Up Barbell Wrist Curl Over A Bench",
    "reverse-wrist-curl": "Palms-Down Wrist Curl Over A Bench",
    "tricep-pushdown": "Triceps Pushdown",
    "rope-pushdown": "Triceps Pushdown - Rope Attachment",
    "reverse-grip-pushdown": "Reverse Grip Triceps Pushdown",
    "skull-crusher": "Lying Close-Grip Barbell Triceps Extension Behind The Head",
    "dumbbell-skull-crusher": "Lying Dumbbell Tricep Extension",
    "overhead-tricep-extension": "Standing Overhead Barbell Triceps Extension",
    "cable-overhead-extension": "Cable Rope Overhead Triceps Extension",
    "tricep-kickback": "Tricep Dumbbell Kickback",
    "tricep-dip": "Dips - Triceps Version",
    "chest-dip": "Dips - Chest Version",
    "bench-dip": "Bench Dips",
    "weighted-chest-dip": "Weighted Bench Dip",
    # --- chest isolation
    "dumbbell-fly": "Dumbbell Flyes",
    "incline-dumbbell-fly": "Incline Dumbbell Flyes",
    "cable-fly": "Flat Bench Cable Flyes",
    "high-to-low-cable-fly": "Incline Cable Flye",
    "pec-deck": "Butterfly",
    "dumbbell-pullover": "Straight-Arm Dumbbell Pullover",
    # --- legs
    "leg-extension": "Leg Extensions",
    "single-leg-extension": "Single-Leg Leg Extension",
    "lying-leg-curl": "Lying Leg Curls",
    "standing-calf-raise": "Standing Calf Raises",
    "single-leg-calf-raise": "Dumbbell Seated One-Leg Calf Raise",
    "donkey-calf-raise": "Donkey Calf Raises",
    "leg-press-calf-raise": "Calf Press On The Leg Press Machine",
    "single-leg-press": "Narrow Stance Leg Press",
    "walking-lunge": "Barbell Walking Lunge",
    "reverse-lunge": "Dumbbell Rear Lunge",
    "jumping-lunge": "Lunge Sprint",
    "split-squat": "Barbell Side Split Squat",
    "step-up": "Dumbbell Step Ups",
    "hip-abduction": "Thigh Abductor",
    "hip-adduction": "Thigh Adductor",
    # --- core
    "crunch": "Crunches",
    "bicycle-crunch": "Air Bike",
    "machine-crunch": "Ab Crunch Machine",
    "stability-ball-crunch": "Exercise Ball Crunch",
    "decline-sit-up": "Decline Crunch",
    "hanging-knee-raise": "Hanging Leg Raise",
    "lying-leg-raise": "Flat Bench Lying Leg Raise",
    "captains-chair-leg-raise": "Knee/Hip Raise On Parallel Bars",
    "ab-wheel-rollout": "Ab Roller",
    "barbell-rollout": "Barbell Ab Rollout",
    "side-plank": "Push Up to Side Plank",
    "wood-chop": "Standing Cable Wood Chop",
    "flutter-kick": "Flutter Kicks",
    "mountain-climber": "Mountain Climbers",
    # --- carries, conditioning, olympic
    "kettlebell-swing": "One-Arm Kettlebell Swings",
    "kettlebell-clean": "Kettlebell Dead Clean",
    "turkish-get-up": "Kettlebell Turkish Get-Up (Squat style)",
    "sled-pull": "Sled Row",
    "trap-bar-shrug": "Barbell Shrug",
    "cable-shrug": "Cable Shrugs",
    "log-press": "Log Lift",
    "atlas-stone-lift": "Atlas Stones",
    "jump-rope": "Rope Jumping",
    "rowing-machine": "Rowing, Stationary",
    "stationary-bike": "Bicycling, Stationary",
    "spin-bike": "Bicycling, Stationary",
    "treadmill-run": "Running, Treadmill",
    "treadmill-walk": "Walking, Treadmill",
    "incline-walk": "Walking, Treadmill",
    "elliptical": "Elliptical Trainer",
    "stair-climber": "Stairmaster",
    # --- mobility
    "calf-stretch": "Standing Gastrocnemius Calf Stretch",
    "hip-flexor-stretch": "Kneeling Hip Flexor",
    "shoulder-dislocate": "Shoulder Circles",
    "cat-cow": "Cat Stretch",
    "thoracic-rotation": "Torso Rotation",
    "foam-roll-it-band": "Iliotibial Tract SMR",
    "foam-roll-quads": "Quadriceps SMR",
    "foam-roll-back": "Latissimus Dorsi SMR",
}


@dataclass(frozen=True, slots=True)
class ImportReport:
    matched: int
    media_rows: int
    unmatched: tuple[str, ...]
    broken_aliases: tuple[str, ...]

    @property
    def coverage_pct(self) -> float:
        total = self.matched + len(self.unmatched)
        return 0.0 if total == 0 else self.matched / total * 100


def _normalise(name: str) -> str:
    lowered = name.lower().replace("-", " ").replace("_", " ").replace("/", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", lowered)).strip()


async def fetch_catalogue(url: str = CATALOGUE_URL) -> list[dict[str, Any]]:
    """One large JSON document, fetched whole. It is about a megabyte."""
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload: list[dict[str, Any]] = response.json()
    return payload


def load_catalogue(path: Path) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return payload


async def import_media(
    session: AsyncSession,
    catalogue: list[dict[str, Any]],
    *,
    image_origin: str = DEFAULT_IMAGE_ORIGIN,
    replace: bool = True,
    dry_run: bool = False,
) -> ImportReport:
    """Attach photographs to the catalogue, matching strictly.

    ``replace`` clears the existing rows for a matched exercise first, so re-running is
    idempotent rather than accumulating duplicate photographs of the same movement.
    """
    by_name = {_normalise(entry["name"]): entry for entry in catalogue}

    # A stale alias is a defect worth stopping for: it means an exercise silently loses
    # its pictures, which nobody would notice from the outside.
    broken = tuple(
        sorted(slug for slug, name in ALIASES.items() if _normalise(name) not in by_name)
    )

    result = await session.execute(
        select(ExerciseModel).where(ExerciseModel.owner_user_id.is_(None))
    )
    ours = list(result.scalars().all())

    matched: list[tuple[UUID, list[str]]] = []
    unmatched: list[str] = []

    for exercise in ours:
        entry = by_name.get(_normalise(exercise.name))
        if entry is None:
            aliased = ALIASES.get(exercise.slug)
            entry = by_name.get(_normalise(aliased)) if aliased else None
        if entry is None:
            unmatched.append(exercise.slug)
            continue

        images = [f"{image_origin.rstrip('/')}/{path}" for path in entry.get("images", [])]
        if images:
            matched.append((exercise.id, images))
        else:
            unmatched.append(exercise.slug)

    rows = sum(len(images) for _, images in matched)

    if not dry_run:
        for exercise_id, images in matched:
            if replace:
                await session.execute(
                    delete(ExerciseMediaModel).where(ExerciseMediaModel.exercise_id == exercise_id)
                )
            for order, url in enumerate(images):
                session.add(
                    ExerciseMediaModel(
                        id=uuid7(),
                        exercise_id=exercise_id,
                        media_type="image",
                        url=url,
                        sort_order=order,
                    )
                )
        await session.commit()

    report = ImportReport(
        matched=len(matched),
        media_rows=rows,
        unmatched=tuple(sorted(unmatched)),
        broken_aliases=broken,
    )
    logger.info(
        "exercise_media_imported",
        matched=report.matched,
        media_rows=report.media_rows,
        unmatched=len(report.unmatched),
        broken_aliases=len(report.broken_aliases),
        dry_run=dry_run,
    )
    return report


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Attach demonstration photographs to exercises.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the rows. Without it the run reports coverage and changes nothing.",
    )
    parser.add_argument(
        "--image-origin",
        default=DEFAULT_IMAGE_ORIGIN,
        help="Where image paths resolve against. Point this at your own mirror.",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="Read the catalogue from disk instead of fetching it.",
    )
    args = parser.parse_args()

    configure_logging()
    catalogue = load_catalogue(args.from_file) if args.from_file else await fetch_catalogue()

    database = Database(get_settings())
    async with database.session_factory() as session:
        report = await import_media(
            session,
            catalogue,
            image_origin=args.image_origin,
            dry_run=not args.apply,
        )
    await database.dispose()

    print(f"matched   : {report.matched}")
    print(f"media rows: {report.media_rows}")
    print(f"coverage  : {report.coverage_pct:.0f}%")
    print(f"unmatched : {len(report.unmatched)}")
    if report.unmatched:
        print("            " + ", ".join(report.unmatched[:12]) + " ...")

    if report.broken_aliases:
        # Non-zero exit: a stale alias means an exercise silently loses its pictures,
        # which is invisible from the outside and would otherwise go unnoticed for months.
        raise SystemExit(
            "Aliases no longer resolving upstream: " + ", ".join(report.broken_aliases)
        )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
