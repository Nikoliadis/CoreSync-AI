import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  CATEGORIES,
  CATEGORY_BLURBS,
  CATEGORY_LABELS,
  type NotificationPreferences,
  notificationKeys,
  notificationsApi,
  quietHoursLabel,
  toggleCategory,
} from "@/features/notifications/api";
import {
  type PermissionState,
  permissionState,
  requestAndRegister,
} from "@/features/notifications/push";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

const QUIET_PRESETS = [
  { label: null, start: null, end: null },
  { label: "22:00 – 07:00", start: 22, end: 7 },
  { label: "23:00 – 08:00", start: 23, end: 8 },
] as const;

/**
 * Who is allowed to interrupt you, and when.
 *
 * Per-category rather than one master switch. Somebody who wants to hear about a personal
 * record but not a weekly summary must be able to say exactly that — given only "all or
 * nothing" they choose nothing, and the channel is gone permanently.
 *
 * Account and security messages have no toggle. They are not a preference, and a switch
 * that does not switch anything is worse than no switch.
 */
export default function NotificationPreferencesScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const prefs = useQuery({
    queryKey: notificationKeys.preferences(),
    queryFn: notificationsApi.preferences,
  });

  const [permission, setPermission] = useState<PermissionState>("undetermined");
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    void permissionState().then(setPermission);
  }, []);

  const ask = async () => {
    setAsking(true);
    try {
      // Registers the token as part of granting, so there is no window where permission
      // is on and the server still has nowhere to send.
      setPermission(await requestAndRegister());
    } finally {
      setAsking(false);
    }
  };

  const update = useMutation({
    mutationFn: notificationsApi.updatePreferences,
    onSuccess: (updated) => {
      // Written straight back rather than invalidated: a switch that flicks back while a
      // refetch is in flight looks like the setting did not take.
      queryClient.setQueryData<NotificationPreferences>(notificationKeys.preferences(), updated);
    },
  });

  const current = prefs.data;
  const enabled = current?.enabledCategories ?? [];

  if (prefs.isLoading || !current) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  const activeQuiet = quietHoursLabel(current);

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <Text variant="h3" style={styles.grow}>
          {t("notifications.title")}
        </Text>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
          <Text tone="accent">{t("common.done")}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {permission !== "granted" && (
          // The prompt is asked here rather than on launch, after the categories below
          // have said what the notifications actually are. iOS grants exactly one
          // chance to ask, and spending it on a cold start is spending it on someone
          // who has no idea what they are agreeing to.
          <Card style={styles.card}>
            <Text variant="overline" tone="muted">
              {t("notifications.turnOn")}
            </Text>
            <Text variant="caption" tone="secondary">
              {permission === "denied"
                ? t("notifications.permissionDenied")
                : permission === "unsupported"
                  ? t("notifications.permissionUnsupported")
                  : t("notifications.permissionPitch")}
            </Text>
            {permission === "undetermined" && (
              <Button
                label={asking ? t("notifications.asking") : t("notifications.allow")}
                disabled={asking}
                onPress={() => void ask()}
              />
            )}
            {permission === "denied" && (
              <Button
                label={t("notifications.openSettings")}
                variant="secondary"
                onPress={() => void Linking.openSettings()}
              />
            )}
          </Card>
        )}

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("notifications.delivery")}
          </Text>
          <Row
            label={t("notifications.push")}
            detail={
              permission === "granted"
                ? t("notifications.pushOnThisDevice")
                : t("notifications.pushNeedsPermission")
            }
            value={current.pushEnabled && permission === "granted"}
            onChange={(value) => update.mutate({ pushEnabled: value })}
          />
          <Row
            label={t("notifications.email")}
            detail={t("notifications.emailDetail")}
            value={current.emailEnabled}
            onChange={(value) => update.mutate({ emailEnabled: value })}
          />
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("notifications.whatToSend")}
          </Text>
          {CATEGORIES.map((category) => (
            <Row
              key={category}
              label={CATEGORY_LABELS[category]}
              detail={CATEGORY_BLURBS[category]}
              value={enabled.includes(category)}
              onChange={(value) =>
                update.mutate({ enabledCategories: toggleCategory(enabled, category, value) })
              }
            />
          ))}
          <Text variant="caption" tone="muted">
            {t("notifications.alwaysSent")}
          </Text>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("notifications.quietHours")}
          </Text>
          <Text variant="caption" tone="muted">
            {t("notifications.quietHoursBody")}
          </Text>
          <View style={styles.presets}>
            {QUIET_PRESETS.map((preset) => {
              const selected =
                preset.start === null ? activeQuiet === null : activeQuiet === preset.label;
              return (
                <Pressable
                  key={preset.label ?? "off"}
                  onPress={() =>
                    update.mutate(
                      preset.start === null
                        ? // `clearQuietHours` exists because null means "unchanged" in a
                          // partial update, so there is no other way to remove them.
                          { clearQuietHours: true }
                        : { quietHoursStart: preset.start, quietHoursEnd: preset.end },
                    )
                  }
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  style={[
                    styles.preset,
                    {
                      borderColor: selected ? theme.accent : theme.border,
                      backgroundColor: selected ? `${theme.accent}1a` : "transparent",
                    },
                  ]}
                >
                  <Text variant="caption" tone={selected ? "default" : "muted"}>
                    {/* A null label is the "off" preset — its wording is translated,
                        while the clock ranges are numerals that read the same in both. */}
                    {preset.label ?? t("notifications.off")}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </Card>
      </ScrollView>
    </Screen>
  );
}

function Row({
  label,
  detail,
  value,
  onChange,
}: {
  label: string;
  detail: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  const theme = useTheme();
  return (
    <View style={styles.row}>
      <View style={styles.rowText}>
        <Text variant="body">{label}</Text>
        <Text variant="caption" tone="muted">
          {detail}
        </Text>
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        accessibilityLabel={label}
        trackColor={{ true: theme.accent, false: theme.border }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  grow: { flex: 1 },
  close: { paddingVertical: space.sm },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  card: { gap: space.sm },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, minHeight: 48 },
  rowText: { flex: 1, gap: 2 },
  presets: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  preset: {
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: space.md,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
  },
});
