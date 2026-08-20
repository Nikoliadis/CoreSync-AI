"""ORM model for earned achievements."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from coresync.infrastructure.database.base import Base


class UserAchievementModel(Base):
    """One row per achievement a user has earned.

    The composite primary key is the guarantee: an achievement cannot be awarded twice
    even if the evaluator runs concurrently, because the second insert violates the key
    rather than quietly creating a duplicate. There is no `revoked_at` — nothing here
    is ever taken away (docs/09 §1).
    """

    __tablename__ = "user_achievements"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # The definition's code, not a foreign key: definitions live in code and are
    # versioned with it, so a database row referencing a retired one still reads fine.
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (Index("ix_user_achievements_user", "user_id", text("earned_at DESC")),)
