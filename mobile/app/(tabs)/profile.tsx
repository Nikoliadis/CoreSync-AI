import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ChevronRight } from "lucide-react-native";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { achievementKeys, achievementsApi } from "@/features/achievements/api";
import { goalKeys, goalSummary, goalsApi } from "@/features/goals/api";
import { ageFrom, heightLabel, settingsApi, settingsKeys } from "@/features/settings/api";
import { SUPPORTED_LOCALES, useI18n, useTranslate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { HIT_SIZE, radius, space, useTheme, useThemePreference, type ThemePreference } from "@/theme";

const THEME_OPTIONS: readonly ThemePreference[] = ["system", "dark", "light"];

export default function ProfileScreen() {
  const t = useTranslate();
  const router = useRouter();
  const me = useQuery({ queryKey: goalKeys.me(), queryFn: goalsApi.me });
  const achievements = useQuery({
    queryKey: achievementKeys.list(),
    queryFn: achievementsApi.list,
  });
  const profile = useQuery({ queryKey: settingsKeys.me(), queryFn: settingsApi.me });
  const user = useAuth((state) => state.user);
  const { preference, setPreference } = useThemePreference();
  const { locale, setLocale } = useI18n();

  const themeLabels: Record<ThemePreference, string> = {
    system: t("profile.themeSystem"),
    dark: t("profile.themeDark"),
    light: t("profile.themeLight"),
  };

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text variant="h1">{t("tabs.profile")}</Text>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("profile.personal").toUpperCase()}
          </Text>
          <NavRow
            label={user?.displayName ?? "—"}
            detail={
              [profile.data?.profile ? heightLabel(profile.data.profile.heightCm, profile.data.settings.unitSystem) : null,
               ageFrom(profile.data?.profile?.dateOfBirth ?? null) !== null
                 ? `${String(ageFrom(profile.data?.profile?.dateOfBirth ?? null))} years`
                 : null,
              ]
                .filter(Boolean)
                .join(" · ") || (user?.email ?? "")
            }
            onPress={() => router.push("/settings/profile")}
          />
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("settings.plan")}
          </Text>
          <NavRow
            label={t("settings.goalAndTargets")}
            detail={goalSummary(me.data?.goal ?? null) ?? t("goals.notSet")}
            onPress={() => router.push("/goals")}
          />
          <NavRow
            label={t("progress.title")}
            detail={t("settings.progressDetail")}
            onPress={() => router.push("/progress")}
          />
          <NavRow
            label={t("achievements.title")}
            detail={
              achievements.data
                ? `${achievements.data.earnedCount} of ${achievements.data.totalCount} earned`
                : t("achievements.badgesAndStreaks")
            }
            onPress={() => router.push("/achievements")}
          />
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("profile.theme").toUpperCase()}
          </Text>
          <View style={styles.chips}>
            {THEME_OPTIONS.map((option) => (
              <Chip
                key={option}
                label={themeLabels[option]}
                active={preference === option}
                onPress={() => setPreference(option)}
              />
            ))}
          </View>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("profile.language").toUpperCase()}
          </Text>
          <View style={styles.chips}>
            {SUPPORTED_LOCALES.map((option) => (
              <Chip
                key={option}
                label={option.toUpperCase()}
                active={locale === option}
                onPress={() => setLocale(option)}
              />
            ))}
          </View>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("settings.app")}
          </Text>
          <NavRow
            label={t("notifications.title")}
            detail={t("settings.notificationsDetail")}
            onPress={() => router.push("/notifications/preferences")}
          />
          <NavRow
            label={t("settings.title")}
            detail={t("settings.settingsDetail")}
            onPress={() => router.push("/settings")}
          />
        </Card>
      </ScrollView>
    </Screen>
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
    <Text
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      variant="caption"
      style={[
        styles.chip,
        {
          borderColor: active ? theme.accent : theme.border,
          backgroundColor: active ? `${theme.accent}1a` : "transparent",
          color: theme.text,
        },
      ]}
    >
      {label}
    </Text>
  );
}

function NavRow({
  label,
  detail,
  onPress,
}: {
  label: string;
  detail: string;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${label}. ${detail}`}
      style={({ pressed }) => [styles.navRow, { opacity: pressed ? 0.6 : 1 }]}
    >
      <View style={styles.navText}>
        <Text variant="body">{label}</Text>
        <Text variant="caption" tone="muted" numberOfLines={1}>
          {detail}
        </Text>
      </View>
      <ChevronRight size={18} color={theme.textMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  navRow: { flexDirection: "row", alignItems: "center", gap: space.sm, minHeight: 48 },
  navText: { flex: 1, gap: 2 },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  card: { gap: space.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    minHeight: HIT_SIZE,
    lineHeight: HIT_SIZE,
    paddingHorizontal: space.lg,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
  },
});
