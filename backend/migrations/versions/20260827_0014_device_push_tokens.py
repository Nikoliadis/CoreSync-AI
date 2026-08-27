"""Make `user_devices` usable for push delivery (Phase 6).

The table has existed since the first migration with a `push_token` column that nothing
ever wrote to. Everything downstream was built and waiting — `channels_for` already
refuses to queue a push when the user has no token, and the dispatcher already skips a
channel with no sender — so the only thing standing between the app and a working push
was the registration path itself.

Two additions:

**`is_active`.** A push token dies for reasons that have nothing to do with the user:
the app is uninstalled, notification permission is revoked, the OS rotates the token.
Expo reports this as `DeviceNotRegistered`, and the correct response is to stop sending
to that device — not to delete the row, which would lose the record that the device ever
existed and let a stale token be re-registered by a retry that was already in flight.

**A unique index on `push_token`.** A token identifies exactly one installation. If the
same token appears against two rows the dispatcher sends twice, and if it appears against
two *users* — which happens when a phone is handed on, or an account is switched in the
app — the wrong person receives the notification. Uniqueness makes that a database error
rather than a privacy incident. Partial, because `NULL` means "registered but no token
yet" and several of those must coexist.

Revision ID: 0014_device_push_tokens
Revises: 0013_erased_status
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_device_push_tokens"
down_revision: str | None = "0013_erased_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_devices",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Partial on purpose: NULL tokens are rows that registered before a token was
    # available, and there can be many of those.
    op.create_index(
        "uq_user_devices_push_token",
        "user_devices",
        ["push_token"],
        unique=True,
        postgresql_where=sa.text("push_token IS NOT NULL"),
    )

    # The dispatcher's hot path: "every deliverable device for this user".
    op.create_index(
        "ix_user_devices_deliverable",
        "user_devices",
        ["user_id"],
        postgresql_where=sa.text("is_active AND push_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_user_devices_deliverable", table_name="user_devices")
    op.drop_index("uq_user_devices_push_token", table_name="user_devices")
    op.drop_column("user_devices", "is_active")
