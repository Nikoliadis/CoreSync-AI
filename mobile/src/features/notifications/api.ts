import { api } from "@/lib/api/client";

/**
 * Notifications, and who is allowed to send them.
 *
 * Categories exist so somebody can silence one kind without silencing all of them.
 * Someone who wants PR celebrations but not weekly reports has to be able to say so, or
 * they turn the lot off and the channel is gone for good.
 *
 * `system` is deliberately absent from the toggles below. Account and security messages
 * are not a preference, and offering a switch that does not switch anything is worse than
 * offering none.
 */

export const CATEGORIES = [
  "workout_reminder",
  "pr_celebration",
  "streak_risk",
  "insight_ready",
  "weekly_report",
] as const;

export type Category = (typeof CATEGORIES)[number];

export const CATEGORY_LABELS: Record<Category, string> = {
  workout_reminder: "Workout reminders",
  pr_celebration: "Personal records",
  streak_risk: "Streak at risk",
  insight_ready: "Coach insights",
  weekly_report: "Weekly report",
};

export const CATEGORY_BLURBS: Record<Category, string> = {
  workout_reminder: "A nudge on the days you usually train.",
  pr_celebration: "When you beat a record.",
  streak_risk: "Before a streak you have built runs out.",
  insight_ready: "When the coach has noticed something.",
  weekly_report: "A summary of the week, once a week.",
};

export type Notification = {
  id: string;
  category: string;
  title: string;
  body: string;
  deepLink: string | null;
  data: Record<string, unknown>;
  readAt: string | null;
  createdAt: string | null;
  isRead: boolean;
};

export type NotificationPreferences = {
  enabledCategories: string[];
  pushEnabled: boolean;
  emailEnabled: boolean;
  quietHoursStart: number | null;
  quietHoursEnd: number | null;
};

export const notificationKeys = {
  all: ["notifications"] as const,
  list: () => [...notificationKeys.all, "list"] as const,
  preferences: () => [...notificationKeys.all, "preferences"] as const,
};

export const notificationsApi = {
  list: (unreadOnly = false) =>
    api.get<{ notifications: Notification[]; unreadCount: number }>("/v1/notifications", {
      query: { limit: 50, unreadOnly },
    }),

  markRead: (notificationId: string) =>
    api.post<void>(`/v1/notifications/${notificationId}/read`, {}),

  markAllRead: () => api.post<{ marked: number }>("/v1/notifications/read-all", {}),

  preferences: () =>
    api.get<NotificationPreferences>("/v1/notifications/preferences"),

  updatePreferences: (changes: {
    enabledCategories?: string[];
    pushEnabled?: boolean;
    emailEnabled?: boolean;
    quietHoursStart?: number;
    quietHoursEnd?: number;
    /**
     * Explicit, because `null` means "unchanged" everywhere else in a partial update
     * and there would otherwise be no way to say "remove my quiet hours".
     */
    clearQuietHours?: boolean;
  }) => api.patch<NotificationPreferences>("/v1/notifications/preferences", changes),
};

/**
 * Toggle one category on or off, returning the full list to send.
 *
 * The API takes the complete set rather than a delta, so the caller has to compute it.
 * Doing that inline in an onPress is how a category gets silently dropped when two
 * toggles are tapped quickly.
 */
export function toggleCategory(
  enabled: readonly string[],
  category: Category,
  on: boolean,
): string[] {
  const next = new Set(enabled);
  if (on) next.add(category);
  else next.delete(category);
  // Ordered by the canonical list so the payload is stable and diffable, and unknown
  // categories the server may have added are preserved rather than dropped by us.
  const known = CATEGORIES.filter((item) => next.has(item));
  const unknown = [...next].filter((item) => !(CATEGORIES as readonly string[]).includes(item));
  return [...known, ...unknown];
}

/** `22:00 – 07:00`, or null when quiet hours are not set. */
export function quietHoursLabel(prefs: NotificationPreferences | undefined): string | null {
  if (!prefs || prefs.quietHoursStart === null || prefs.quietHoursEnd === null) return null;
  const pad = (hour: number) => `${String(hour).padStart(2, "0")}:00`;
  return `${pad(prefs.quietHoursStart)} – ${pad(prefs.quietHoursEnd)}`;
}

/** `2h ago`, `3d ago`, or the date beyond a week. */
export function relativeTime(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";

  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 60) return "just now";

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;

  return new Date(then).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Where a notification should take you.
 *
 * Returns null for anything unrecognised rather than guessing. A deep link that lands on
 * the wrong screen is more annoying than one that does nothing, because the user has to
 * work out where they are before they can get back.
 */
export function routeFor(notification: Notification): string | null {
  const link = notification.deepLink;
  if (!link) return null;

  // Server links are app-relative paths already; anything else is not ours to follow.
  if (link.startsWith("/")) return link;
  return null;
}
