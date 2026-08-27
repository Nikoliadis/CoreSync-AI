import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Award, Lock } from "lucide-react-native";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  type Achievement,
  achievementKeys,
  achievementsApi,
  byCategory,
  CATEGORY_LABELS,
  progressLabel,
  progressPct,
  tierColour,
} from "@/features/achievements/api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * What you have earned, and what you are closest to earning.
 *
 * Unearned badges show a progress bar and "7 of 10" rather than a padlock. A grid of grey
 * locks says nothing about whether the next one is two workouts away or two hundred, and
 * reads like a paywall in an app that has none.
 */
export default function AchievementsScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();

  const list = useQuery({
    queryKey: achievementKeys.list(),
    queryFn: achievementsApi.list,
  });

  if (list.isLoading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  if (list.isError || !list.data) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button label={t("common.retry")} variant="ghost" onPress={() => void list.refetch()} />
          <Button label={t("common.cancel")} variant="ghost" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const { achievements, earnedCount, totalCount } = list.data;
  const groups = byCategory(achievements);

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={list.isRefetching}
            onRefresh={() => void list.refetch()}
            tintColor={theme.textMuted}
          />
        }
      >
        <View style={styles.header}>
          <Text variant="h1" style={styles.grow}>
            {t("achievements.title")}
          </Text>
          <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
            <Text tone="accent">{t("common.done")}</Text>
          </Pressable>
        </View>

        <Text variant="caption" tone="muted" tabular>
          {t("achievements.earnedOf", { earned: earnedCount, total: totalCount })}
        </Text>

        {groups.map(([category, items]) => (
          <View key={category} style={styles.group}>
            <Text variant="overline" tone="muted">
              {CATEGORY_LABELS[category].toUpperCase()}
            </Text>
            {items.map((achievement) => (
              <Badge key={achievement.code} achievement={achievement} />
            ))}
          </View>
        ))}
      </ScrollView>
    </Screen>
  );
}

function Badge({ achievement }: { achievement: Achievement }) {
  const theme = useTheme();
  const colour = tierColour(achievement.tier);
  const pct = progressPct(achievement);

  return (
    <Card
      style={styles.badge}
      accessible
      accessibilityLabel={
        achievement.earned
          ? `${achievement.name}, earned. ${achievement.description}`
          : `${achievement.name}, not yet earned. ${progressLabel(achievement)}. ${achievement.description}`
      }
    >
      <View style={styles.badgeHead}>
        <View
          style={[
            styles.medal,
            {
              backgroundColor: achievement.earned ? `${colour}22` : theme.surfaceWell,
              borderColor: achievement.earned ? colour : theme.border,
            },
          ]}
        >
          {achievement.earned ? (
            <Award size={20} color={colour} />
          ) : (
            <Lock size={16} color={theme.textMuted} />
          )}
        </View>

        <View style={styles.badgeText}>
          <Text variant="body" numberOfLines={1}>
            {achievement.name}
          </Text>
          <Text variant="caption" tone="muted">
            {achievement.description}
          </Text>
        </View>
      </View>

      {!achievement.earned && (
        <View style={styles.progressRow}>
          <View style={[styles.track, { backgroundColor: theme.surfaceWell }]}>
            <View
              style={[
                styles.fill,
                {
                  backgroundColor: colour,
                  // Clamped client-side too: a remote number fed straight into a width
                  // would render the bar outside its own container.
                  width: `${pct}%`,
                },
              ]}
            />
          </View>
          <Text variant="caption" tone="muted" style={styles.progressLabel} tabular>
            {progressLabel(achievement)}
          </Text>
        </View>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  header: { flexDirection: "row", alignItems: "center", gap: space.md },
  close: { paddingVertical: space.sm },
  grow: { flex: 1 },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  group: { gap: space.sm },
  badge: { gap: space.sm },
  badgeHead: { flexDirection: "row", alignItems: "center", gap: space.md },
  medal: {
    width: 44,
    height: 44,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { flex: 1, gap: 2 },
  progressRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  track: { flex: 1, height: 6, borderRadius: 3, overflow: "hidden" },
  fill: { height: 6, borderRadius: 3 },
  progressLabel: { minWidth: 88, textAlign: "right" },
});
