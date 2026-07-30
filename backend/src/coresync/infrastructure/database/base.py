"""SQLAlchemy declarative base and shared column conventions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit constraint naming. Without this, Alembic autogenerates unnamed constraints
# that cannot be dropped in a downgrade, and error messages say "constraint_1".
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        pk = getattr(self, "id", None) or getattr(self, "user_id", None)
        return f"<{type(self).__name__} {pk}>"


class TimestampMixin:
    """created_at / updated_at on every table.

    ``updated_at`` is maintained by a database trigger as well as by ``onupdate`` — the
    trigger is the one that cannot be bypassed by a bulk UPDATE or a manual fix.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Soft delete for user content only.

    This is an undo affordance, not privacy compliance — GDPR erasure is a separate hard
    delete job (docs/11 §8).
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


def utcnow_column(**kwargs: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), **kwargs)
