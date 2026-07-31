"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Check } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { PageShell } from "@/components/layout/page-header";
import { TopBar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CATEGORY_LABELS,
  UNSILENCEABLE,
  notificationsApi,
  type Notification,
} from "@/features/notifications/api";
import { cn } from "@/lib/utils/cn";

export default function NotificationsPage() {
  const queryClient = useQueryClient();

  const list = useQuery({ queryKey: ["notifications"], queryFn: () => notificationsApi.list() });
  const preferences = useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: notificationsApi.preferences,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };

  const markRead = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: invalidate });

  const markAll = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: (result) => {
      invalidate();
      toast.success(result.marked > 0 ? `Marked ${result.marked} as read` : "Nothing unread");
    },
  });

  const updatePrefs = useMutation({
    mutationFn: notificationsApi.updatePreferences,
    onSuccess: () => {
      invalidate();
      toast.success("Preferences saved");
    },
    onError: () => toast.error("Couldn't save that", { description: "Try again in a moment." }),
  });

  const notifications = list.data?.notifications ?? [];
  const unread = list.data?.unreadCount ?? 0;
  const prefs = preferences.data;

  function toggleCategory(category: string, enabled: boolean) {
    if (!prefs) return;
    const next = enabled
      ? [...new Set([...prefs.enabledCategories, category])]
      : prefs.enabledCategories.filter((c) => c !== category);
    updatePrefs.mutate({ enabledCategories: next });
  }

  return (
    <>
      <TopBar
        title="Notifications"
        action={
          unread > 0 ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => markAll.mutate()}
              loading={markAll.isPending}
            >
              <Check className="h-4 w-4" aria-hidden />
              Mark all read
            </Button>
          ) : undefined
        }
      />

      <PageShell className="max-w-3xl">
        <div className="flex flex-col gap-4">
          <Card padding={notifications.length > 0 ? "none" : "md"}>
            {list.isLoading && (
              <div className="flex flex-col gap-2 p-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            )}

            {list.isError && (
              <EmptyState
                icon={<Bell className="h-8 w-8" />}
                title="Couldn't load notifications"
                action={<Button onClick={() => list.refetch()}>Try again</Button>}
              />
            )}

            {list.isSuccess && notifications.length === 0 && (
              <EmptyState
                icon={<Bell className="h-8 w-8" />}
                title="Nothing here yet"
                description="Personal records, coach insights and streak reminders will land here."
              />
            )}

            {notifications.length > 0 && (
              <ul className="divide-y divide-border">
                {notifications.map((notification) => (
                  <NotificationRow
                    key={notification.id}
                    notification={notification}
                    onRead={() => markRead.mutate(notification.id)}
                  />
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>What you hear about</CardTitle>
            </CardHeader>

            {preferences.isLoading && <Skeleton className="h-40 w-full" />}

            {prefs && (
              <div className="flex flex-col gap-1">
                {Object.entries(CATEGORY_LABELS).map(([category, label]) => {
                  const locked = UNSILENCEABLE.has(category);
                  const enabled = locked || prefs.enabledCategories.includes(category);
                  return (
                    <label
                      key={category}
                      className={cn(
                        "flex min-h-11 items-center justify-between gap-4 rounded-md px-2",
                        locked ? "opacity-60" : "hover:bg-surface-well",
                      )}
                    >
                      <span className="text-body text-text">{label}</span>
                      <span className="flex items-center gap-2">
                        {/* Stated in words, not just a disabled control — a greyed
                            checkbox with no explanation reads as a bug. */}
                        {locked && <span className="text-caption text-text-muted">Always on</span>}
                        <input
                          type="checkbox"
                          className="h-5 w-5 rounded-sm accent-[var(--color-accent)]"
                          checked={enabled}
                          disabled={locked || updatePrefs.isPending}
                          onChange={(event) => toggleCategory(category, event.target.checked)}
                        />
                      </span>
                    </label>
                  );
                })}

                <div className="mt-3 border-t border-border pt-3">
                  <p className="text-body text-text">Quiet hours</p>
                  <p className="mt-0.5 text-caption text-text-muted">
                    {prefs.quietHoursStart !== null && prefs.quietHoursEnd !== null
                      ? `Nothing between ${String(prefs.quietHoursStart).padStart(2, "0")}:00 and ${String(
                          prefs.quietHoursEnd,
                        ).padStart(2, "0")}:00 your time. Anything raised in that window arrives afterwards rather than being dropped.`
                      : "Off — notifications can arrive at any hour."}
                  </p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3"
                    onClick={() =>
                      updatePrefs.mutate(
                        prefs.quietHoursStart === null
                          ? { quietHoursStart: 22, quietHoursEnd: 7 }
                          : { clearQuietHours: true },
                      )
                    }
                    loading={updatePrefs.isPending}
                  >
                    {prefs.quietHoursStart === null ? "Enable 22:00 to 07:00" : "Turn off"}
                  </Button>
                </div>
              </div>
            )}
          </Card>

          {/* Stated rather than implied: the API and preferences are live, but no
              provider is wired, so nothing is actually delivered yet. */}
          <p className="flex items-center gap-2 rounded-md border border-border bg-surface-well p-3 text-caption text-text-muted">
            <BellOff className="h-4 w-4 shrink-0" aria-hidden />
            Push and email delivery aren&apos;t switched on yet — these preferences are saved, and
            in-app notifications still appear here.
          </p>
        </div>
      </PageShell>
    </>
  );
}

function NotificationRow({
  notification,
  onRead,
}: {
  notification: Notification;
  onRead: () => void;
}) {
  const body = (
    <div className="flex items-start gap-3 px-4 py-3">
      {/* Unread is marked by a shape and by weight, never by colour alone. */}
      <span
        className={cn(
          "mt-1.5 h-2 w-2 shrink-0 rounded-full",
          notification.isRead ? "bg-transparent" : "bg-accent",
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className={cn("text-body", notification.isRead ? "text-text-secondary" : "text-text")}>
          {notification.title}
        </p>
        <p className="mt-0.5 text-caption text-text-muted">{notification.body}</p>
      </div>
      {!notification.isRead && <span className="sr-only">Unread</span>}
    </div>
  );

  return (
    <li>
      {notification.deepLink ? (
        <Link href={notification.deepLink} onClick={onRead} className="block hover:bg-surface-well">
          {body}
        </Link>
      ) : (
        <button
          type="button"
          onClick={onRead}
          className="block w-full text-left hover:bg-surface-well"
        >
          {body}
        </button>
      )}
    </li>
  );
}
