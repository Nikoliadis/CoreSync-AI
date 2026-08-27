import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Settings2 } from "lucide-react-native";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  type Notification,
  notificationKeys,
  notificationsApi,
  relativeTime,
  routeFor,
} from "@/features/notifications/api";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

/**
 * What the app has told you.
 *
 * Opening a notification marks it read and follows its link. Both, because the two are
 * one intention — nobody taps a notification meaning "mark this read but stay here".
 */
export default function NotificationsScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: notificationKeys.list(),
    queryFn: () => notificationsApi.list(),
  });

  const open = (notification: Notification) => {
    if (!notification.isRead) {
      // Optimistic: the row should stop looking unread under the finger, and a failed
      // mark-read is not worth interrupting navigation for.
      queryClient.setQueryData<{ notifications: Notification[]; unreadCount: number }>(
        notificationKeys.list(),
        (current) =>
          current
            ? {
                notifications: current.notifications.map((item) =>
                  item.id === notification.id ? { ...item, isRead: true } : item,
                ),
                unreadCount: Math.max(0, current.unreadCount - 1),
              }
            : current,
      );
      void notificationsApi.markRead(notification.id).catch(() => {
        // Left as-is. The next fetch corrects it.
      });
    }

    const route = routeFor(notification);
    if (route) router.push(route);
  };

  const markAll = () => {
    void notificationsApi.markAllRead().then(() => {
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    });
  };

  const notifications = list.data?.notifications ?? [];
  const unread = list.data?.unreadCount ?? 0;

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <View style={styles.grow}>
          <Text variant="h3">Notifications</Text>
          {unread > 0 && (
            <Text variant="caption" tone="muted">
              {unread} unread
            </Text>
          )}
        </View>
        <Pressable
          onPress={() => router.push("/notifications/preferences")}
          accessibilityRole="button"
          accessibilityLabel="Notification settings"
          hitSlop={8}
          style={styles.icon}
        >
          <Settings2 size={18} color={theme.textMuted} />
        </Pressable>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
          <Text tone="accent">{t("common.done")}</Text>
        </Pressable>
      </View>

      {list.isLoading ? (
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      ) : (
        <FlatList
          data={notifications}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.list}
          refreshing={list.isRefetching}
          onRefresh={() => void list.refetch()}
          ListHeaderComponent={
            unread > 0 ? (
              <Button
                label="Mark all as read"
                variant="ghost"
                size="sm"
                onPress={markAll}
                style={styles.markAll}
              />
            ) : null
          }
          ListEmptyComponent={
            <View style={styles.centre}>
              <Text tone="secondary">Nothing yet.</Text>
              <Text variant="caption" tone="muted" style={styles.centred}>
                Reminders, records and coach insights land here.
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() => open(item)}
              accessibilityRole="button"
              accessibilityLabel={`${item.title}. ${item.body}${item.isRead ? "" : ". Unread"}`}
              style={({ pressed }) => [
                styles.row,
                {
                  borderBottomColor: theme.border,
                  backgroundColor: item.isRead ? "transparent" : `${theme.accent}0d`,
                  opacity: pressed ? 0.6 : 1,
                },
              ]}
            >
              <View
                style={[
                  styles.dot,
                  { backgroundColor: item.isRead ? "transparent" : theme.accent },
                ]}
              />
              <View style={styles.rowText}>
                <Text numberOfLines={1}>{item.title}</Text>
                <Text variant="caption" tone="secondary" numberOfLines={2}>
                  {item.body}
                </Text>
                <Text variant="caption" tone="muted">
                  {relativeTime(item.createdAt)}
                </Text>
              </View>
            </Pressable>
          )}
        />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  grow: { flex: 1 },
  icon: { padding: space.xs },
  close: { paddingVertical: space.sm, paddingLeft: space.xs },
  list: { paddingBottom: space.xxl },
  markAll: { alignSelf: "flex-end", marginRight: space.lg, marginTop: space.sm },
  centre: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: space.sm,
    padding: space.xl,
  },
  centred: { textAlign: "center" },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  rowText: { flex: 1, gap: 2 },
});
