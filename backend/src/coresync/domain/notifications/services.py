"""Scheduling rules for notifications.

Pure functions over times and preferences, so every edge case here is unit-testable
without a database, a clock or a push provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from coresync.domain.notifications.entities import (
    NotificationCategory,
    NotificationChannel,
    NotificationPreferences,
)

# Categories urgent enough to ignore quiet hours would defeat the point of quiet
# hours. None currently qualify: a PR celebration at 03:00 is not a service the user
# asked for. Kept as an explicit empty set so adding one is a deliberate decision.
BYPASSES_QUIET_HOURS: frozenset[NotificationCategory] = frozenset()


def _zone(timezone: str) -> tzinfo:
    try:
        return ZoneInfo(timezone)
    except Exception:
        # A bad timezone must not stop a notification. UTC is wrong for the user but
        # silence is worse, and the misconfiguration surfaces in the logs elsewhere.
        return UTC


def is_within_quiet_hours(
    moment: datetime, preferences: NotificationPreferences, timezone: str
) -> bool:
    """Whether a moment falls inside the user's quiet window, in their local time."""
    if not preferences.has_quiet_hours:
        return False

    start = preferences.quiet_hours_start
    end = preferences.quiet_hours_end
    assert start is not None and end is not None  # guarded by has_quiet_hours

    local_hour = moment.astimezone(_zone(timezone)).hour

    if start < end:
        # A daytime window, e.g. 09:00-17:00.
        return start <= local_hour < end
    # The common case wraps midnight, e.g. 22:00-07:00: inside means "late enough" or
    # "early enough", which a naive `start <= h < end` gets backwards for every hour.
    return local_hour >= start or local_hour < end


def next_send_time(
    moment: datetime,
    preferences: NotificationPreferences,
    timezone: str,
    *,
    category: NotificationCategory,
) -> datetime:
    """When this notification may actually be delivered.

    Quiet hours **defer**, they do not drop. A missed workout reminder that is simply
    discarded is a feature that silently stops working overnight; one that arrives at
    07:00 is the behaviour the user expected when they set the window.
    """
    if category in BYPASSES_QUIET_HOURS:
        return moment
    if not is_within_quiet_hours(moment, preferences, timezone):
        return moment

    end_hour = preferences.quiet_hours_end
    assert end_hour is not None

    zone = _zone(timezone)
    local = moment.astimezone(zone)
    release = local.replace(hour=end_hour, minute=0, second=0, microsecond=0)

    # If the window ends earlier today than "now", the release is tomorrow — the
    # 23:30-with-a-07:00-window case.
    if release <= local:
        release = release + timedelta(days=1)

    return release.astimezone(UTC)


def channels_for(
    category: NotificationCategory,
    preferences: NotificationPreferences,
    *,
    has_push_token: bool,
) -> list[NotificationChannel]:
    """Which channels this notification should be queued on.

    In-app is always included for an allowed category: it is the record the user sees
    when they open the app, and it costs nothing to deliver. Push is only queued when
    there is somewhere to send it — an outbox row for a user with no device is a
    guaranteed failure that would burn retries.
    """
    channels: list[NotificationChannel] = []

    if preferences.allows(category, NotificationChannel.IN_APP):
        channels.append(NotificationChannel.IN_APP)
    if has_push_token and preferences.allows(category, NotificationChannel.PUSH):
        channels.append(NotificationChannel.PUSH)
    # Email is reserved for things worth an inbox interruption. A PR celebration by
    # email is how an app ends up in a spam filter.
    if category in {NotificationCategory.WEEKLY_REPORT, NotificationCategory.SYSTEM} and (
        preferences.allows(category, NotificationChannel.EMAIL)
    ):
        channels.append(NotificationChannel.EMAIL)

    return channels
