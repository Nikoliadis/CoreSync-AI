import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { RefreshControl, ScrollView, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { dashboardApi, dashboardKeys } from "@/features/dashboard/api";
import { useTranslate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { radius, space, useTheme } from "@/theme";

const round = (value: string | null | undefined) => Math.round(Number(value ?? 0));

export default function HomeScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const user = useAuth((state) => state.user);

  const diary = useQuery({ queryKey: dashboardKeys.diary(), queryFn: dashboardApi.diary });
  const streak = useQuery({ queryKey: dashboardKeys.streak(), queryFn: dashboardApi.streak });
  const weight = useQuery({
    queryKey: dashboardKeys.weight(),
    queryFn: dashboardApi.latestWeight,
  });
  const active = useQuery({
    queryKey: dashboardKeys.active(),
    queryFn: dashboardApi.activeSession,
  });

  const refreshing =
    diary.isRefetching || streak.isRefetching || weight.isRefetching || active.isRefetching;

  const refresh = () => {
    void diary.refetch();
    void streak.refetch();
    void weight.refetch();
    void active.refetch();
  };

  const totals = diary.data?.totals;
  const target = diary.data?.targets ? round(diary.data.targets.calories) : null;
  const eaten = round(totals?.calories);

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
            tintColor={theme.textMuted}
          />
        }
      >
        <Text variant="h1" style={styles.greeting}>
          {t("home.greeting", { name: user?.displayName ?? "" })}
        </Text>

        {/* An in-progress workout is the most urgent thing on the screen, so it goes
            above everything else and nothing competes with it. */}
        {active.data && (
          <Card style={[styles.card, { borderColor: theme.accent }]}>
            <Text variant="overline" tone="accent">
              {t("workouts.active").toUpperCase()}
            </Text>
            <Text variant="h2" style={styles.tight}>
              {active.data.name}
            </Text>
            <Button
              label={t("workouts.start")}
              style={styles.spaced}
              onPress={() => router.push("/workout/active")}
            />
          </Card>
        )}

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("home.todaysCalories").toUpperCase()}
          </Text>
          <View style={styles.calorieRow}>
            <Text variant="display" tabular>
              {eaten}
            </Text>
            {target !== null && (
              <Text variant="body" tone="secondary" style={styles.calorieTarget}>
                {t("nutrition.caloriesLeft", { count: Math.max(target - eaten, 0) })}
              </Text>
            )}
          </View>

          {target === null && (
            /* No target is not a failure state — there is nothing to be over or under,
               and a red bar would be inventing a judgement nobody asked for. */
            <Text variant="caption" tone="muted">
              {t("nutrition.noTarget")}
            </Text>
          )}

          <View style={styles.macros}>
            <Macro label={t("home.protein")} grams={round(totals?.proteinG)} color={theme.chart[0] ?? theme.accent} />
            <Macro label={t("home.carbs")} grams={round(totals?.carbsG)} color={theme.chart[1] ?? theme.accent} />
            <Macro label={t("home.fat")} grams={round(totals?.fatG)} color={theme.chart[2] ?? theme.accent} />
          </View>
        </Card>

        <View style={styles.row}>
          <Stat
            label={t("home.water")}
            value={`${round(diary.data?.waterMl)}`}
            unit="ml"
          />
          <Stat
            label={t("home.weight")}
            value={weight.data ? Number(weight.data.weightKg).toFixed(1) : "—"}
            unit="kg"
          />
          <Stat
            label={t("home.streak")}
            value={`${streak.data?.current ?? 0}`}
            unit="d"
          />
        </View>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("home.recentActivity").toUpperCase()}
          </Text>
          {diary.data?.entries.length ? (
            diary.data.entries.slice(0, 5).map((entry) => (
              <View key={entry.id} style={[styles.entry, { borderTopColor: theme.border }]}>
                <Text numberOfLines={1} style={styles.entryName}>
                  {entry.displayName}
                </Text>
                <Text tone="secondary" tabular>
                  {round(entry.macros.calories)}
                </Text>
              </View>
            ))
          ) : (
            <Text variant="caption" tone="muted" style={styles.spaced}>
              {t("home.nothingYet")}
            </Text>
          )}
        </Card>
      </ScrollView>
    </Screen>
  );
}

function Macro({ label, grams, color }: { label: string; grams: number; color: string }) {
  return (
    <View style={styles.macro}>
      <View style={[styles.swatch, { backgroundColor: color }]} />
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Text variant="h3" tabular>
        {grams}g
      </Text>
    </View>
  );
}

function Stat({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <Card style={styles.stat}>
      <Text variant="caption" tone="muted">
        {label}
      </Text>
      <Text variant="h2" tabular>
        {value}
        <Text variant="caption" tone="muted">
          {" "}
          {unit}
        </Text>
      </Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  greeting: { marginBottom: space.xs },
  card: { gap: space.sm },
  tight: { marginTop: space.xs },
  spaced: { marginTop: space.sm },
  calorieRow: { flexDirection: "row", alignItems: "baseline", gap: space.md },
  calorieTarget: { flexShrink: 1 },
  macros: { flexDirection: "row", gap: space.lg, marginTop: space.sm },
  macro: { gap: 2 },
  swatch: { width: 20, height: 3, borderRadius: radius.full },
  row: { flexDirection: "row", gap: space.md },
  stat: { flex: 1, gap: space.xs },
  entry: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: space.md,
    paddingVertical: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  entryName: { flex: 1 },
});
