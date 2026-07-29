"""Reference data: muscle groups, muscles, equipment and exercise categories.

Ids are derived deterministically from the slug with UUIDv5, so re-running the seed
updates rows rather than creating duplicates, and the same exercise has the same id in
every environment. That matters for support ("what is 019...?") and for fixtures that
reference a catalog entry by id across a database rebuild.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# One fixed namespace for every catalog id. Chosen once and never changed — changing it
# would re-key the entire catalog and orphan every logged workout.
CATALOG_NAMESPACE = UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")


def catalog_id(kind: str, slug: str) -> UUID:
    return uuid5(CATALOG_NAMESPACE, f"{kind}:{slug}")


# (slug, name, sort_order)
MUSCLE_GROUPS: tuple[tuple[str, str, int], ...] = (
    ("chest", "Chest", 1),
    ("back", "Back", 2),
    ("shoulders", "Shoulders", 3),
    ("arms", "Arms", 4),
    ("legs", "Legs", 5),
    ("core", "Core", 6),
    ("full_body", "Full Body", 7),
    ("cardio", "Cardio", 8),
)

# (slug, name, muscle_group_slug)
MUSCLES: tuple[tuple[str, str, str], ...] = (
    ("upper_chest", "Upper Chest", "chest"),
    ("mid_chest", "Mid Chest", "chest"),
    ("lower_chest", "Lower Chest", "chest"),
    ("lats", "Lats", "back"),
    ("traps", "Trapezius", "back"),
    ("rhomboids", "Rhomboids", "back"),
    ("lower_back", "Lower Back", "back"),
    ("teres_major", "Teres Major", "back"),
    ("front_delts", "Front Delts", "shoulders"),
    ("side_delts", "Side Delts", "shoulders"),
    ("rear_delts", "Rear Delts", "shoulders"),
    ("rotator_cuff", "Rotator Cuff", "shoulders"),
    ("biceps", "Biceps", "arms"),
    ("triceps", "Triceps", "arms"),
    ("forearms", "Forearms", "arms"),
    ("brachialis", "Brachialis", "arms"),
    ("quads", "Quadriceps", "legs"),
    ("hamstrings", "Hamstrings", "legs"),
    ("glutes", "Glutes", "legs"),
    ("calves", "Calves", "legs"),
    ("adductors", "Adductors", "legs"),
    ("abductors", "Abductors", "legs"),
    ("hip_flexors", "Hip Flexors", "legs"),
    ("abs", "Abdominals", "core"),
    ("obliques", "Obliques", "core"),
    ("transverse_abs", "Transverse Abdominis", "core"),
    ("erectors", "Spinal Erectors", "core"),
    ("neck", "Neck", "full_body"),
    ("cardiovascular", "Cardiovascular", "cardio"),
)

# (slug, name, is_home_available)
EQUIPMENT: tuple[tuple[str, str, bool], ...] = (
    ("barbell", "Barbell", False),
    ("dumbbell", "Dumbbell", True),
    ("kettlebell", "Kettlebell", True),
    ("machine", "Machine", False),
    ("cable", "Cable Machine", False),
    ("smith_machine", "Smith Machine", False),
    ("bodyweight", "Bodyweight", True),
    ("resistance_band", "Resistance Band", True),
    ("ez_bar", "EZ Bar", False),
    ("trap_bar", "Trap Bar", False),
    ("pull_up_bar", "Pull-up Bar", True),
    ("dip_bars", "Dip Bars", True),
    ("bench", "Bench", True),
    ("incline_bench", "Incline Bench", False),
    ("squat_rack", "Squat Rack", False),
    ("leg_press", "Leg Press Machine", False),
    ("medicine_ball", "Medicine Ball", True),
    ("stability_ball", "Stability Ball", True),
    ("foam_roller", "Foam Roller", True),
    ("trx", "Suspension Trainer", True),
    ("treadmill", "Treadmill", False),
    ("bike", "Exercise Bike", False),
    ("rower", "Rowing Machine", False),
    ("elliptical", "Elliptical", False),
    ("stair_climber", "Stair Climber", False),
    ("jump_rope", "Jump Rope", True),
    ("plate", "Weight Plate", False),
    ("landmine", "Landmine", False),
    ("ab_wheel", "Ab Wheel", True),
    ("sled", "Sled", False),
    ("box", "Plyo Box", False),
    ("none", "No Equipment", True),
)

# (slug, name, sort_order)
CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("strength", "Strength", 1),
    ("olympic", "Olympic Weightlifting", 2),
    ("powerlifting", "Powerlifting", 3),
    ("plyometrics", "Plyometrics", 4),
    ("cardio", "Cardio", 5),
    ("stretching", "Stretching", 6),
    ("mobility", "Mobility", 7),
    ("strongman", "Strongman", 8),
)
