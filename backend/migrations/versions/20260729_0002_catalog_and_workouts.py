"""Exercise catalog, workouts, personal records and activity aggregates (Phase 2).

Hand-written, like 0001. Autogenerate does not emit the generated columns
(``exercises.search_vector``, ``session_sets.estimated_1rm``), the partial unique
indexes that carry the correctness guarantees, or the GIN indexes the catalog search
depends on — and those are the parts that matter.

Revision ID: 0002_catalog_workouts
Revises: 0001_initial
Created: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_catalog_workouts"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table below gets the shared updated_at trigger from 0001.
_TIMESTAMPED = (
    "muscle_groups",
    "muscles",
    "equipment",
    "exercise_categories",
    "exercises",
    "exercise_media",
    "routines",
    "routine_exercises",
    "workout_sessions",
    "session_exercises",
    "session_sets",
)


def upgrade() -> None:
    # btree_gin backs the composite catalog indexes; pg_trgm (from 0001) backs fuzzy
    # exercise search.
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gin"')

    _create_catalog()
    _create_routines()
    _create_sessions()
    _create_records_and_sync()
    _create_aggregates()

    for table in _TIMESTAMPED:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


# ----------------------------------------------------------------------- catalog
def _create_catalog() -> None:
    op.create_table(
        "muscle_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_muscle_groups"),
        sa.UniqueConstraint("slug", name="uq_muscle_groups_slug"),
    )

    op.create_table(
        "muscles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("muscle_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_muscles"),
        sa.UniqueConstraint("slug", name="uq_muscles_slug"),
        sa.ForeignKeyConstraint(
            ["muscle_group_id"],
            ["muscle_groups.id"],
            name="fk_muscles_muscle_group_id_muscle_groups",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_muscles_group", "muscles", ["muscle_group_id"])

    op.create_table(
        "equipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("is_home_available", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_equipment"),
        sa.UniqueConstraint("slug", name="uq_equipment_slug"),
    )

    op.create_table(
        "exercise_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exercise_categories"),
        sa.UniqueConstraint("slug", name="uq_exercise_categories_slug"),
    )

    op.create_table(
        "exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("force_type", sa.String(10), nullable=True),
        sa.Column("mechanic", sa.String(10), nullable=True),
        sa.Column("difficulty", sa.String(15), server_default="intermediate", nullable=False),
        sa.Column("logging_type", sa.String(25), server_default="weight_reps", nullable=False),
        sa.Column("is_unilateral", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Generated, so the search index can never fall behind the row it indexes.
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('simple', coalesce(name,'')), 'A') || "
                "setweight(to_tsvector('simple', coalesce(description,'')), 'C')",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exercises"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["exercise_categories.id"],
            name="fk_exercises_category_id_exercise_categories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_exercises_owner_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "force_type IS NULL OR force_type IN ('push','pull','static')",
            name="ck_exercises_force_type_valid",
        ),
        sa.CheckConstraint(
            "mechanic IS NULL OR mechanic IN ('compound','isolation')",
            name="ck_exercises_mechanic_valid",
        ),
        sa.CheckConstraint(
            "difficulty IN ('beginner','intermediate','advanced')",
            name="ck_exercises_difficulty_valid",
        ),
        sa.CheckConstraint(
            "logging_type IN ('weight_reps','bodyweight_reps','weighted_bodyweight',"
            "'time','distance_time','reps_only')",
            name="ck_exercises_logging_type_valid",
        ),
        # A user cannot mint a "Verified" exercise, whatever the API layer believes.
        sa.CheckConstraint(
            "owner_user_id IS NULL OR is_verified = false",
            name="ck_exercises_custom_not_verified",
        ),
    )
    # Two partial uniques: slugs are unique within the global catalog, and separately
    # within each user's own exercises.
    op.create_index(
        "uq_exercises_slug_global",
        "exercises",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NULL"),
    )
    op.create_index(
        "uq_exercises_slug_user",
        "exercises",
        ["owner_user_id", "slug"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_index("ix_exercises_search", "exercises", ["search_vector"], postgresql_using="gin")
    op.create_index(
        "ix_exercises_name_trgm",
        "exercises",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_exercises_catalog",
        "exercises",
        ["category_id", "difficulty"],
        postgresql_where=sa.text("owner_user_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_exercises_owner",
        "exercises",
        ["owner_user_id"],
        postgresql_where=sa.text("owner_user_id IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_table(
        "exercise_muscles",
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("muscle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("contribution_pct", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("exercise_id", "muscle_id", name="pk_exercise_muscles"),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_exercise_muscles_exercise_id_exercises",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["muscle_id"],
            ["muscles.id"],
            name="fk_exercise_muscles_muscle_id_muscles",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "role IN ('primary','secondary','stabilizer')", name="ck_exercise_muscles_role_valid"
        ),
        sa.CheckConstraint(
            "contribution_pct IS NULL OR contribution_pct BETWEEN 0 AND 100",
            name="ck_exercise_muscles_contribution_range",
        ),
    )
    op.create_index("ix_exercise_muscles_muscle", "exercise_muscles", ["muscle_id", "role"])

    op.create_table(
        "exercise_equipment",
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("exercise_id", "equipment_id", name="pk_exercise_equipment"),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_exercise_equipment_exercise_id_exercises",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["equipment_id"],
            ["equipment.id"],
            name="fk_exercise_equipment_equipment_id_equipment",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_exercise_equipment_item", "exercise_equipment", ["equipment_id"])

    op.create_table(
        "exercise_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(12), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exercise_media"),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_exercise_media_exercise_id_exercises",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "media_type IN ('image','video','animation')", name="ck_exercise_media_media_type_valid"
        ),
    )
    op.create_index("ix_exercise_media_exercise", "exercise_media", ["exercise_id", "sort_order"])

    op.create_table(
        "exercise_instructions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_exercise_instructions"),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_exercise_instructions_exercise_id_exercises",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("exercise_id", "step_number", name="uq_exercise_instruction_step"),
        sa.CheckConstraint("step_number > 0", name="ck_exercise_instructions_step_positive"),
    )

    op.create_table(
        "user_favorite_exercises",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("user_id", "exercise_id", name="pk_user_favorite_exercises"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_favorite_exercises_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_user_favorite_exercises_exercise_id_exercises",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_favorite_exercises_user", "user_favorite_exercises", ["user_id", "created_at"]
    )


# ---------------------------------------------------------------------- routines
def _create_routines() -> None:
    op.create_table(
        "routines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("folder", sa.String(80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_template", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("estimated_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("position", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_routines"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_routines_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 120", name="ck_routines_name_len"),
        sa.CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes BETWEEN 1 AND 600",
            name="ck_routines_estimated_minutes_range",
        ),
        # A template belongs to no one; an owned routine is not a template.
        sa.CheckConstraint(
            "(is_template AND user_id IS NULL) OR (NOT is_template AND user_id IS NOT NULL)",
            name="ck_routines_template_ownership",
        ),
    )
    op.create_index(
        "ix_routines_user",
        "routines",
        ["user_id", "position"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_routines_templates",
        "routines",
        ["position"],
        postgresql_where=sa.text("is_template AND deleted_at IS NULL"),
    )

    op.create_table(
        "routine_exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("routine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("superset_group", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rest_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_routine_exercises"),
        sa.ForeignKeyConstraint(
            ["routine_id"],
            ["routines.id"],
            name="fk_routine_exercises_routine_id_routines",
            ondelete="CASCADE",
        ),
        # RESTRICT: an exercise that appears in someone's plan cannot be deleted out
        # from under it.
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_routine_exercises_exercise_id_exercises",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position > 0", name="ck_routine_exercises_position_positive"),
        sa.CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 3600",
            name="ck_routine_exercises_rest_range",
        ),
        sa.UniqueConstraint("routine_id", "position", name="uq_routine_exercise_position"),
    )
    op.create_index("ix_routine_exercises_routine", "routine_exercises", ["routine_id", "position"])
    op.create_index("ix_routine_exercises_exercise", "routine_exercises", ["exercise_id"])

    op.create_table(
        "routine_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("routine_exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_number", sa.SmallInteger(), nullable=False),
        sa.Column("set_type", sa.String(10), server_default="normal", nullable=False),
        sa.Column("target_reps_min", sa.SmallInteger(), nullable=True),
        sa.Column("target_reps_max", sa.SmallInteger(), nullable=True),
        sa.Column("target_weight_kg", sa.Numeric(6, 2), nullable=True),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("target_distance_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("target_rpe", sa.Numeric(3, 1), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_routine_sets"),
        sa.ForeignKeyConstraint(
            ["routine_exercise_id"],
            ["routine_exercises.id"],
            name="fk_routine_sets_routine_exercise_id_routine_exercises",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("set_number > 0", name="ck_routine_sets_set_number_positive"),
        sa.CheckConstraint(
            "set_type IN ('normal','warmup','drop','failure','amrap')",
            name="ck_routine_sets_set_type_valid",
        ),
        sa.CheckConstraint(
            "target_reps_min IS NULL OR target_reps_max IS NULL "
            "OR target_reps_min <= target_reps_max",
            name="ck_routine_sets_rep_range_ordered",
        ),
        sa.CheckConstraint(
            "target_rpe IS NULL OR target_rpe BETWEEN 1 AND 10",
            name="ck_routine_sets_target_rpe_range",
        ),
        sa.UniqueConstraint("routine_exercise_id", "set_number", name="uq_routine_set_number"),
    )


# ---------------------------------------------------------------------- sessions
def _create_sessions() -> None:
    op.create_table(
        "workout_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("routine_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("total_volume_kg", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("total_sets", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("total_reps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("perceived_effort", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.String(12), server_default="in_progress", nullable=False),
        sa.Column("visibility", sa.String(10), server_default="private", nullable=False),
        sa.Column("client_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workout_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_workout_sessions_user_id_users", ondelete="CASCADE"
        ),
        # SET NULL, not CASCADE. Deleting a routine must never delete workout history —
        # the single most important ON DELETE choice in the schema.
        sa.ForeignKeyConstraint(
            ["routine_id"],
            ["routines.id"],
            name="fk_workout_sessions_routine_id_routines",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress','completed','discarded')",
            name="ck_workout_sessions_status_valid",
        ),
        sa.CheckConstraint(
            "visibility IN ('private','followers','public')",
            name="ck_workout_sessions_visibility_valid",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_workout_sessions_session_times",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_workout_sessions_duration_positive",
        ),
        sa.CheckConstraint(
            "perceived_effort IS NULL OR perceived_effort BETWEEN 1 AND 10",
            name="ck_workout_sessions_effort_range",
        ),
    )
    op.create_index(
        "ix_workout_sessions_user_date",
        "workout_sessions",
        ["user_id", sa.text("local_date DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Offline sync deduplication: a client-named session is one row forever, however many
    # times the phone flushes it.
    op.create_index(
        "uq_workout_sessions_client_id",
        "workout_sessions",
        ["user_id", "client_session_id"],
        unique=True,
        postgresql_where=sa.text("client_session_id IS NOT NULL"),
    )
    # At most one workout in progress per user — a double-tapped "Start workout" on a
    # laggy connection cannot create two.
    op.create_index(
        "uq_workout_sessions_one_in_progress",
        "workout_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress' AND deleted_at IS NULL"),
    )
    op.create_index("ix_workout_sessions_routine", "workout_sessions", ["routine_id"])

    op.create_table(
        "session_exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("superset_group", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rest_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_exercises"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["workout_sessions.id"],
            name="fk_session_exercises_session_id_workout_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_session_exercises_exercise_id_exercises",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position > 0", name="ck_session_exercises_position_positive"),
        sa.CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 3600",
            name="ck_session_exercises_rest_range",
        ),
    )
    op.create_index("ix_session_exercises_session", "session_exercises", ["session_id", "position"])
    op.create_index("ix_session_exercises_exercise", "session_exercises", ["exercise_id"])

    op.create_table(
        "session_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_number", sa.SmallInteger(), nullable=False),
        sa.Column("set_type", sa.String(10), server_default="normal", nullable=False),
        sa.Column("reps", sa.SmallInteger(), nullable=True),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Numeric(10, 2), nullable=True),
        sa.Column("rpe", sa.Numeric(3, 1), nullable=True),
        sa.Column("is_completed", sa.Boolean(), server_default="true", nullable=False),
        # Epley, generated. Capped at 15 reps because the formula diverges beyond that
        # and a "PR" from a 30-rep set is noise, not progress.
        sa.Column(
            "estimated_1rm",
            sa.Numeric(7, 2),
            sa.Computed(
                "CASE WHEN weight_kg IS NOT NULL AND reps IS NOT NULL "
                "AND reps > 0 AND reps <= 15 AND weight_kg > 0 "
                "THEN round(weight_kg * (1 + reps::numeric / 30), 2) END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_sets"),
        sa.ForeignKeyConstraint(
            ["session_exercise_id"],
            ["session_exercises.id"],
            name="fk_session_sets_session_exercise_id_session_exercises",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("set_number > 0", name="ck_session_sets_set_number_positive"),
        sa.CheckConstraint(
            "set_type IN ('normal','warmup','drop','failure','amrap')",
            name="ck_session_sets_set_type_valid",
        ),
        sa.CheckConstraint(
            "reps IS NULL OR reps BETWEEN 0 AND 1000", name="ck_session_sets_reps_range"
        ),
        sa.CheckConstraint(
            "weight_kg IS NULL OR (weight_kg >= 0 AND weight_kg <= 1000)",
            name="ck_session_sets_weight_range",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_session_sets_duration_positive",
        ),
        sa.CheckConstraint(
            "distance_m IS NULL OR distance_m >= 0", name="ck_session_sets_distance_positive"
        ),
        sa.CheckConstraint("rpe IS NULL OR rpe BETWEEN 1 AND 10", name="ck_session_sets_rpe_range"),
        # A set must record something. An empty row is indistinguishable from a real one
        # and silently drags every average down.
        sa.CheckConstraint(
            "reps IS NOT NULL OR duration_seconds IS NOT NULL OR distance_m IS NOT NULL",
            name="ck_session_sets_set_has_payload",
        ),
        sa.UniqueConstraint("session_exercise_id", "set_number", name="uq_session_set_number"),
    )
    op.create_index(
        "ix_session_sets_exercise", "session_sets", ["session_exercise_id", "set_number"]
    )


# --------------------------------------------------- personal records & sync log
def _create_records_and_sync() -> None:
    op.create_table(
        "personal_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("reps_at_value", sa.SmallInteger(), nullable=True),
        sa.Column("session_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("achieved_on", sa.Date(), nullable=False),
        sa.Column("previous_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_personal_records"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_personal_records_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_personal_records_exercise_id_exercises",
            ondelete="CASCADE",
        ),
        # SET NULL so a corrected or deleted set does not erase the achievement.
        sa.ForeignKeyConstraint(
            ["session_set_id"],
            ["session_sets.id"],
            name="fk_personal_records_session_set_id_session_sets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["previous_record_id"],
            ["personal_records.id"],
            name="fk_personal_records_previous_record_id_personal_records",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "record_type IN ('max_weight','max_reps','max_volume_set','est_1rm',"
            "'max_duration','max_distance')",
            name="ck_personal_records_record_type_valid",
        ),
        sa.CheckConstraint("value > 0", name="ck_personal_records_value_positive"),
    )
    # Exactly one current record per (user, exercise, type). History survives on the
    # previous_record_id chain, so "current PRs" stays an index-only lookup.
    op.create_index(
        "uq_personal_records_current",
        "personal_records",
        ["user_id", "exercise_id", "record_type"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_personal_records_user_recent",
        "personal_records",
        ["user_id", sa.text("achieved_on DESC")],
    )
    op.create_index("ix_personal_records_set", "personal_records", ["session_set_id"])
    op.create_index("ix_personal_records_previous", "personal_records", ["previous_record_id"])

    op.create_table(
        "sync_operations",
        sa.Column("op_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("op_id", "user_id", name="pk_sync_operations"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sync_operations_user_id_users", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_sync_operations_user", "sync_operations", ["user_id", "applied_at"])


# -------------------------------------------------------------------- aggregates
def _create_aggregates() -> None:
    op.create_table(
        "daily_activity_summaries",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("workout_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("total_volume_kg", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("total_sets", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("duration_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "volume_by_muscle_group",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("pr_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "local_date", name="pk_daily_activity_summaries"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_daily_activity_summaries_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "workout_count >= 0", name="ck_daily_activity_summaries_workout_count_positive"
        ),
        sa.CheckConstraint(
            "total_volume_kg >= 0", name="ck_daily_activity_summaries_volume_positive"
        ),
        sa.CheckConstraint("total_sets >= 0", name="ck_daily_activity_summaries_sets_positive"),
    )
    op.create_index(
        "ix_daily_activity_user_date",
        "daily_activity_summaries",
        ["user_id", sa.text("local_date DESC")],
    )

    op.create_table(
        "exercise_statistics",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_sessions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_sets", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_volume_kg", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("best_est_1rm", sa.Numeric(7, 2), nullable=True),
        sa.Column("last_performed_on", sa.Date(), nullable=True),
        sa.Column("trend_slope", sa.Numeric(8, 4), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "exercise_id", name="pk_exercise_statistics"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_exercise_statistics_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            name="fk_exercise_statistics_exercise_id_exercises",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "total_sessions >= 0 AND total_sets >= 0", name="ck_exercise_statistics_counts_positive"
        ),
    )
    op.create_index(
        "ix_exercise_statistics_user_recent",
        "exercise_statistics",
        ["user_id", sa.text("last_performed_on DESC")],
    )

    op.create_table(
        "user_streaks",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workout_current", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("workout_longest", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("workout_last_date", sa.Date(), nullable=True),
        sa.Column("nutrition_current", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("nutrition_longest", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("nutrition_last_date", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_streaks"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_streaks_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "workout_current >= 0 AND workout_longest >= workout_current",
            name="ck_user_streaks_workout_streak_sane",
        ),
        sa.CheckConstraint(
            "nutrition_current >= 0 AND nutrition_longest >= nutrition_current",
            name="ck_user_streaks_nutrition_streak_sane",
        ),
    )


def downgrade() -> None:
    for table in _TIMESTAMPED:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")

    op.drop_table("user_streaks")
    op.drop_table("exercise_statistics")
    op.drop_table("daily_activity_summaries")
    op.drop_table("sync_operations")
    op.drop_table("personal_records")
    op.drop_table("session_sets")
    op.drop_table("session_exercises")
    op.drop_table("workout_sessions")
    op.drop_table("routine_sets")
    op.drop_table("routine_exercises")
    op.drop_table("routines")
    op.drop_table("user_favorite_exercises")
    op.drop_table("exercise_instructions")
    op.drop_table("exercise_media")
    op.drop_table("exercise_equipment")
    op.drop_table("exercise_muscles")
    op.drop_table("exercises")
    op.drop_table("exercise_categories")
    op.drop_table("equipment")
    op.drop_table("muscles")
    op.drop_table("muscle_groups")
