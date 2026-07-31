"""/v1/notifications — the in-app list and delivery preferences."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from coresync.application.notifications.use_cases import (
    ListNotificationsUseCase,
    MarkNotificationReadUseCase,
    NotificationPreferencesUseCase,
)
from coresync.domain.notifications.entities import NotificationCategory
from coresync.presentation import dependencies as deps
from coresync.presentation.schemas.common import ErrorResponse
from coresync.presentation.schemas.notifications import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationResponse,
    UpdateNotificationPreferencesRequest,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

MAX_PAGE = 100


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="List notifications",
    description=(
        "Most recent first, with the unread count alongside so the badge does not need "
        "a second request."
    ),
)
async def list_notifications(
    user: deps.CurrentUser,
    use_case: Annotated[ListNotificationsUseCase, Depends(deps.list_notifications_use_case)],
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> NotificationListResponse:
    items, unread = await use_case.execute(user.id, limit=limit, unread_only=unread_only)
    return NotificationListResponse(
        notifications=[NotificationResponse.model_validate(item) for item in items],
        unread_count=unread,
    )


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Mark one as read",
    description="Idempotent — marking an already-read notification succeeds unchanged.",
)
async def mark_read(
    notification_id: UUID,
    user: deps.CurrentUser,
    use_case: Annotated[MarkNotificationReadUseCase, Depends(deps.mark_notification_read_use_case)],
) -> None:
    await use_case.execute(notification_id, user.id)


@router.post(
    "/read-all",
    response_model=MarkAllReadResponse,
    summary="Mark everything as read",
)
async def mark_all_read(
    user: deps.CurrentUser,
    use_case: Annotated[MarkNotificationReadUseCase, Depends(deps.mark_notification_read_use_case)],
) -> MarkAllReadResponse:
    return MarkAllReadResponse(marked=await use_case.mark_all(user.id))


@router.get(
    "/preferences",
    response_model=NotificationPreferencesResponse,
    summary="Delivery preferences",
    description=(
        "Quiet hours are local wall-clock hours, not UTC — they keep meaning the same "
        "thing after travel and after the clocks change."
    ),
)
async def get_preferences(
    user: deps.CurrentUser,
    use_case: Annotated[NotificationPreferencesUseCase, Depends(deps.notification_prefs_use_case)],
) -> NotificationPreferencesResponse:
    preferences = await use_case.get(user.id)
    return NotificationPreferencesResponse(
        enabled_categories=sorted(c.value for c in preferences.enabled_categories),
        push_enabled=preferences.push_enabled,
        email_enabled=preferences.email_enabled,
        quiet_hours_start=preferences.quiet_hours_start,
        quiet_hours_end=preferences.quiet_hours_end,
    )


@router.patch(
    "/preferences",
    response_model=NotificationPreferencesResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Update delivery preferences",
    description=(
        "Partial update. System notices cannot be silenced — account and security "
        "messages are not a preference."
    ),
)
async def update_preferences(
    body: UpdateNotificationPreferencesRequest,
    user: deps.CurrentUser,
    use_case: Annotated[NotificationPreferencesUseCase, Depends(deps.notification_prefs_use_case)],
) -> NotificationPreferencesResponse:
    preferences = await use_case.update(
        user.id,
        enabled_categories=(
            {NotificationCategory(c) for c in body.enabled_categories}
            if body.enabled_categories is not None
            else None
        ),
        push_enabled=body.push_enabled,
        email_enabled=body.email_enabled,
        quiet_hours_start=body.quiet_hours_start,
        quiet_hours_end=body.quiet_hours_end,
        clear_quiet_hours=body.clear_quiet_hours,
    )
    return NotificationPreferencesResponse(
        enabled_categories=sorted(c.value for c in preferences.enabled_categories),
        push_enabled=preferences.push_enabled,
        email_enabled=preferences.email_enabled,
        quiet_hours_start=preferences.quiet_hours_start,
        quiet_hours_end=preferences.quiet_hours_end,
    )
