"""Notification scheduling.

Quiet hours are where this gets interesting: the common window wraps midnight, which
is exactly the case a naive range check gets wrong for every hour of the night.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from coresync.domain.notifications.entities import (
    DeliveryStatus,
    Notification,
    NotificationCategory,
    NotificationChannel,
    NotificationPreferences,
    OutboxEntry,
)
from coresync.domain.notifications.services import (
    channels_for,
    is_within_quiet_hours,
    next_send_time,
)

USER = uuid4()


def prefs(**overrides: object) -> NotificationPreferences:
    base = NotificationPreferences.defaults(USER)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def at(hour: int, minute: int = 0) -> datetime:
    """A UTC moment. Tests that care about local time say so via the timezone arg."""
    return datetime(2026, 7, 31, hour, minute, tzinfo=UTC)


class TestQuietHoursWrappingMidnight:
    """The default window, 22:00-07:00."""

    @pytest.mark.parametrize("hour", [22, 23, 0, 3, 6])
    def test_night_hours_are_quiet(self, hour: int) -> None:
        assert is_within_quiet_hours(at(hour), prefs(), "UTC") is True

    @pytest.mark.parametrize("hour", [7, 8, 12, 18, 21])
    def test_waking_hours_are_not(self, hour: int) -> None:
        assert is_within_quiet_hours(at(hour), prefs(), "UTC") is False

    def test_the_boundary_is_inclusive_at_the_start(self) -> None:
        assert is_within_quiet_hours(at(22, 0), prefs(), "UTC") is True

    def test_the_boundary_is_exclusive_at_the_end(self) -> None:
        """07:00 is the first deliverable minute, not the last silent one."""
        assert is_within_quiet_hours(at(7, 0), prefs(), "UTC") is False


class TestQuietHoursWithinOneDay:
    def test_a_daytime_window_is_handled(self) -> None:
        daytime = prefs(quiet_hours_start=9, quiet_hours_end=17)
        assert is_within_quiet_hours(at(12), daytime, "UTC") is True
        assert is_within_quiet_hours(at(8), daytime, "UTC") is False
        assert is_within_quiet_hours(at(18), daytime, "UTC") is False


class TestQuietHoursDisabled:
    def test_no_window_means_never_quiet(self) -> None:
        off = prefs(quiet_hours_start=None, quiet_hours_end=None)
        assert is_within_quiet_hours(at(3), off, "UTC") is False

    def test_an_equal_start_and_end_is_treated_as_off(self) -> None:
        """Otherwise it would read as a 24-hour window and silence everything."""
        degenerate = prefs(quiet_hours_start=22, quiet_hours_end=22)
        assert degenerate.has_quiet_hours is False
        assert is_within_quiet_hours(at(23), degenerate, "UTC") is False


class TestTimezones:
    def test_quiet_hours_follow_the_users_local_clock(self) -> None:
        """The same instant is quiet in one place and not in another.

        03:00 UTC is 06:00 in Athens (quiet, the window runs to 07:00) but 20:00 the
        previous evening in Los Angeles (not quiet yet).
        """
        assert is_within_quiet_hours(at(3), prefs(), "Europe/Athens") is True
        assert is_within_quiet_hours(at(3), prefs(), "America/Los_Angeles") is False

    def test_los_angeles_night_is_quiet(self) -> None:
        """06:00 UTC is 23:00 the previous evening in Los Angeles."""
        assert is_within_quiet_hours(at(6), prefs(), "America/Los_Angeles") is True

    def test_the_same_instant_differs_by_timezone(self) -> None:
        """14:00 UTC is the middle of the Athens afternoon and 07:00 in LA."""
        moment = at(14)
        assert is_within_quiet_hours(moment, prefs(), "Europe/Athens") is False
        assert is_within_quiet_hours(moment, prefs(), "America/Los_Angeles") is False

    def test_an_unknown_timezone_falls_back_rather_than_raising(self) -> None:
        """A bad stored timezone must never stop a notification."""
        assert is_within_quiet_hours(at(12), prefs(), "Mars/Olympus_Mons") is False


class TestDeferral:
    def test_a_notification_outside_quiet_hours_sends_immediately(self) -> None:
        moment = at(15)
        assert (
            next_send_time(moment, prefs(), "UTC", category=NotificationCategory.WORKOUT_REMINDER)
            == moment
        )

    def test_a_late_night_notification_is_held_until_morning(self) -> None:
        release = next_send_time(
            at(23, 30), prefs(), "UTC", category=NotificationCategory.PR_CELEBRATION
        )
        assert release.hour == 7
        # Next day, not the 07:00 that has already passed.
        assert release.day == 1
        assert release.month == 8

    def test_an_early_morning_notification_waits_only_hours(self) -> None:
        release = next_send_time(at(3), prefs(), "UTC", category=NotificationCategory.STREAK_RISK)
        assert release.hour == 7
        assert release.day == 31

    def test_deferral_is_never_a_drop(self) -> None:
        """The whole rule: quiet hours delay, they do not discard."""
        release = next_send_time(at(2), prefs(), "UTC", category=NotificationCategory.INSIGHT_READY)
        assert release > at(2)

    def test_deferral_respects_the_users_timezone(self) -> None:
        """02:00 in Athens is 23:00 UTC; the release is 07:00 Athens, i.e. 04:00 UTC."""
        release = next_send_time(
            at(23), prefs(), "Europe/Athens", category=NotificationCategory.WEEKLY_REPORT
        )
        assert release.astimezone(UTC).hour == 4


class TestPreferences:
    def test_a_silenced_category_is_refused(self) -> None:
        muted = prefs(enabled_categories={NotificationCategory.PR_CELEBRATION})
        assert muted.allows(NotificationCategory.WEEKLY_REPORT, NotificationChannel.PUSH) is False
        assert muted.allows(NotificationCategory.PR_CELEBRATION, NotificationChannel.PUSH) is True

    def test_system_notices_cannot_be_silenced(self) -> None:
        """Account and security messages are not a preference."""
        muted = prefs(enabled_categories=set(), push_enabled=False)
        assert muted.allows(NotificationCategory.SYSTEM, NotificationChannel.PUSH) is True

    def test_disabling_push_leaves_in_app_intact(self) -> None:
        no_push = prefs(push_enabled=False)
        assert no_push.allows(NotificationCategory.STREAK_RISK, NotificationChannel.PUSH) is False
        assert no_push.allows(NotificationCategory.STREAK_RISK, NotificationChannel.IN_APP) is True


class TestChannelSelection:
    def test_push_is_skipped_without_a_device_token(self) -> None:
        """An outbox row with nowhere to send is a guaranteed failure."""
        channels = channels_for(NotificationCategory.PR_CELEBRATION, prefs(), has_push_token=False)
        assert NotificationChannel.PUSH not in channels
        assert NotificationChannel.IN_APP in channels

    def test_push_is_used_when_a_device_exists(self) -> None:
        channels = channels_for(NotificationCategory.PR_CELEBRATION, prefs(), has_push_token=True)
        assert NotificationChannel.PUSH in channels

    def test_a_pr_celebration_never_goes_to_email(self) -> None:
        """That is how an app ends up in a spam filter."""
        channels = channels_for(NotificationCategory.PR_CELEBRATION, prefs(), has_push_token=True)
        assert NotificationChannel.EMAIL not in channels

    def test_a_weekly_report_does(self) -> None:
        channels = channels_for(NotificationCategory.WEEKLY_REPORT, prefs(), has_push_token=True)
        assert NotificationChannel.EMAIL in channels

    def test_a_silenced_category_produces_no_channels(self) -> None:
        muted = prefs(enabled_categories=set())
        assert channels_for(NotificationCategory.STREAK_RISK, muted, has_push_token=True) == []


class TestOutboxRetries:
    def make(self) -> OutboxEntry:
        return OutboxEntry.create(
            notification_id=uuid4(),
            user_id=USER,
            channel=NotificationChannel.PUSH,
            scheduled_for=at(12),
        )

    def test_a_failure_stays_pending_while_attempts_remain(self) -> None:
        entry = self.make()
        entry.record_failure("token rejected", at=at(12, 5))
        assert entry.status is DeliveryStatus.PENDING
        assert entry.attempts == 1

    def test_it_gives_up_after_three_attempts(self) -> None:
        """A queue that retries forever is a queue that never drains."""
        entry = self.make()
        for _ in range(3):
            entry.record_failure("token rejected", at=at(12))
        assert entry.status is DeliveryStatus.FAILED
        assert entry.is_exhausted

    def test_success_records_the_time_and_clears_the_error(self) -> None:
        entry = self.make()
        entry.record_failure("transient", at=at(12))
        entry.record_success(at(12, 1))
        assert entry.status is DeliveryStatus.SENT
        assert entry.sent_at == at(12, 1)
        assert entry.last_error is None

    def test_a_skip_is_not_a_failure(self) -> None:
        """Opting out must not show up in delivery failure metrics."""
        entry = self.make()
        entry.skip("category disabled")
        assert entry.status is DeliveryStatus.SKIPPED
        assert entry.attempts == 0

    def test_an_enormous_provider_error_is_truncated(self) -> None:
        entry = self.make()
        entry.record_failure("x" * 5000, at=at(12))
        assert entry.last_error is not None
        assert len(entry.last_error) == 500


class TestNotificationEntity:
    def test_marking_read_is_idempotent(self) -> None:
        """A second tap must not move the timestamp."""
        notification = Notification.create(
            user_id=USER,
            category=NotificationCategory.PR_CELEBRATION,
            title="New bench PR",
            body="102.5 kg for 3 — up 2.5 kg.",
        )
        notification.mark_read(at(10))
        notification.mark_read(at(11))
        assert notification.read_at == at(10)

    def test_a_new_notification_is_unread(self) -> None:
        notification = Notification.create(
            user_id=USER,
            category=NotificationCategory.SYSTEM,
            title="Welcome",
            body="Glad you're here.",
        )
        assert notification.is_read is False
