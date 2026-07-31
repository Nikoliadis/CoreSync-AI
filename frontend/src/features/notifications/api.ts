import { api } from "@/lib/api/client";

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

export const CATEGORY_LABELS: Record<string, string> = {
  workout_reminder: "Workout reminders",
  pr_celebration: "Personal records",
  streak_risk: "Streak at risk",
  insight_ready: "Coach insights",
  weekly_report: "Weekly report",
  system: "Account & security",
};

/** Mirrors the backend: account and security messages are not a preference. */
export const UNSILENCEABLE = new Set(["system"]);

export const notificationsApi = {
  list: (unreadOnly = false) =>
    api.get<{ notifications: Notification[]; unreadCount: number }>("/v1/notifications", {
      query: { unreadOnly, limit: 50 },
    }),

  markRead: (id: string) => api.post<void>(`/v1/notifications/${id}/read`),

  markAllRead: () => api.post<{ marked: number }>("/v1/notifications/read-all"),

  preferences: () => api.get<NotificationPreferences>("/v1/notifications/preferences"),

  updatePreferences: (patch: Partial<NotificationPreferences> & { clearQuietHours?: boolean }) =>
    api.patch<NotificationPreferences>("/v1/notifications/preferences", patch),
};
