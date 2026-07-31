"""Wire schemas for notifications."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from coresync.presentation.schemas.common import ApiModel

_CATEGORIES = (
    "workout_reminder",
    "pr_celebration",
    "streak_risk",
    "insight_ready",
    "weekly_report",
    "system",
)


class NotificationResponse(ApiModel):
    id: UUID
    category: str
    title: str
    body: str
    deep_link: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime | None = None
    is_read: bool = False


class NotificationListResponse(ApiModel):
    notifications: list[NotificationResponse]
    # Returned alongside the page so the badge does not need a second request.
    unread_count: int


class MarkAllReadResponse(ApiModel):
    marked: int


class NotificationPreferencesResponse(ApiModel):
    enabled_categories: list[str]
    push_enabled: bool
    email_enabled: bool
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None


class UpdateNotificationPreferencesRequest(ApiModel):
    """Every field optional — this is a partial update."""

    enabled_categories: list[str] | None = None
    push_enabled: bool | None = None
    email_enabled: bool | None = None
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    # Explicit, because `null` in a partial update means "unchanged" everywhere else
    # and there would otherwise be no way to say "remove my quiet hours".
    clear_quiet_hours: bool = False

    @model_validator(mode="after")
    def _validate(self) -> UpdateNotificationPreferencesRequest:
        if self.enabled_categories is not None:
            unknown = sorted(set(self.enabled_categories) - set(_CATEGORIES))
            if unknown:
                raise ValueError(f"Unknown categories: {', '.join(unknown)}")

        # A window needs both ends. Setting one alone would leave the pair
        # half-configured and the behaviour ambiguous.
        if not self.clear_quiet_hours:
            start, end = self.quiet_hours_start, self.quiet_hours_end
            if (start is None) != (end is None):
                raise ValueError("Set both quiet hour bounds, or use clearQuietHours.")
        return self
