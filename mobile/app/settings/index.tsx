import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
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
import { settingsApi, settingsKeys } from "@/features/settings/api";
import { useTranslate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { radius, space, useTheme } from "@/theme";

/**
 * The public policy page, served by the web app at `/privacy`.
 *
 * Configurable because the host differs per environment, and a staging build that opens
 * the production policy is showing the wrong document. Falls back to the production URL
 * so a build with no web URL configured still reaches something real rather than
 * nothing at all.
 */
const PRIVACY_POLICY_URL = `${process.env.EXPO_PUBLIC_WEB_URL ?? "https://coresync.app"}/privacy`;

/**
 * Units, privacy, data, and the way out.
 *
 * Account deletion is here rather than behind a support email because both stores require
 * it in-app, and because how hard a product makes it to leave says what it thinks of the
 * people using it.
 */
export default function SettingsScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const logout = useAuth((state) => state.logout);

  const [deleting, setDeleting] = useState(false);

  const me = useQuery({ queryKey: settingsKeys.me(), queryFn: settingsApi.me });

  const update = useMutation({
    mutationFn: settingsApi.updateSettings,
    onSuccess: (settings) => {
      // Written back rather than invalidated: a switch that flicks back while a refetch
      // is in flight looks like the setting did not take.
      queryClient.setQueryData(settingsKeys.me(), (current: unknown) =>
        current && typeof current === "object" ? { ...current, settings } : current,
      );
    },
  });

  const settings = me.data?.settings;

  const confirmDelete = () => {
    Alert.alert(
      t("settings.deleteTitle"),
      t("settings.deleteBody"),
      [
        { text: t("common.cancel"), style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            void (async () => {
              setDeleting(true);
              try {
                const result = await settingsApi.deleteAccount();
                // Stated with the actual date rather than a vague reassurance: the grace
                // period is the difference between reversible and not.
                Alert.alert(t("settings.deleteScheduled"), result.message, [
                  { text: "OK", onPress: () => void logout() },
                ]);
              } catch (error) {
                console.warn("could not delete account", error);
                Alert.alert(t("common.errorTitle"), t("common.errorBody"));
              } finally {
                setDeleting(false);
              }
            })();
          },
        },
      ],
    );
  };

  if (me.isLoading || !settings) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <Text variant="h3" style={styles.grow}>
          {t("settings.title")}
        </Text>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
          <Text tone="accent">{t("common.done")}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("settings.units")}
          </Text>
          <View style={styles.chips}>
            {(["metric", "imperial"] as const).map((option) => (
              <Chip
                key={option}
                label={option === "metric" ? t("settings.metric") : t("settings.imperial")}
                active={settings.unitSystem === option}
                onPress={() => update.mutate({ unitSystem: option })}
              />
            ))}
          </View>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("settings.privacy")}
          </Text>
          <Row
            label={t("settings.improveCoach")}
            detail={t("settings.improveCoachDetail")}
            value={settings.aiTrainingOptIn}
            onChange={(value) => update.mutate({ aiTrainingOptIn: value })}
          />
          <Row
            label={t("settings.productEmails")}
            detail={t("settings.productEmailsDetail")}
            value={settings.marketingEmailOptIn}
            onChange={(value) => update.mutate({ marketingEmailOptIn: value })}
          />
          <Pressable
            onPress={() => void Linking.openURL(PRIVACY_POLICY_URL)}
            accessibilityRole="link"
            style={styles.link}
          >
            <Text variant="caption" tone="accent">
              {t("settings.privacyPolicy")}
            </Text>
          </Pressable>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("settings.account")}
          </Text>
          <Text variant="caption" tone="muted">
            {me.data?.user.email}
          </Text>
          <Button
            label={t("auth.logout")}
            variant="ghost"
            style={{ borderColor: theme.border }}
            onPress={() => void logout()}
          />
          <Pressable
            onPress={confirmDelete}
            disabled={deleting}
            accessibilityRole="button"
            accessibilityLabel={t("settings.deleteAccountLabel")}
            style={styles.danger}
          >
            <Text variant="caption" style={{ color: theme.critical }}>
              {deleting ? t("settings.working") : t("settings.deleteAccount")}
            </Text>
          </Pressable>
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

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ selected: active }}
      style={[
        styles.chip,
        {
          borderColor: active ? theme.accent : theme.border,
          backgroundColor: active ? `${theme.accent}1a` : "transparent",
        },
      ]}
    >
      <Text variant="caption" tone={active ? "default" : "secondary"}>
        {label}
      </Text>
    </Pressable>
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
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: space.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  link: { paddingVertical: space.xs },
  danger: { alignSelf: "center", paddingVertical: space.sm },
});
