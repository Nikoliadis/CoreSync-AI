import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { duration, relativeDay, volume } from "@/features/workouts/history-list-api";
import { sessionApi, sessionKeys } from "@/features/workouts/session-api";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

/**
 * A workout that already happened.
 *
 * Read-only on purpose. Editing a finished session would mean re-running personal-record
 * detection, the daily aggregate, the per-exercise statistics and the streak — the whole
 * chain `CompleteSessionUseCase` runs in one transaction. Until that has a considered
 * answer, showing the record honestly beats letting somebody quietly rewrite it.
 */
export default function SessionDetailScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const { sessionId } = useLocalSearchParams<{ sessionId: string }>();

  const session = useQuery({
    queryKey: sessionKeys.detail(sessionId),
    queryFn: () => sessionApi.get(sessionId),
    enabled: Boolean(sessionId),
  });

  if (session.isLoading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  if (session.isError || !session.data) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button label={t("common.retry")} variant="ghost" onPress={() => void session.refetch()} />
          <Button label={t("common.cancel")} variant="ghost" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const workout = session.data;

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <View style={styles.grow}>
          <Text variant="h2" numberOfLines={1}>
            {workout.name}
          </Text>
          <Text variant="caption" tone="muted" tabular>
            {relativeDay(workout.localDate)} · {duration(workout.durationSeconds)}
          </Text>
        </View>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
          <Text tone="accent">{t("common.done")}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <Card style={styles.totals}>
          <Total label={t("workouts.sets")} value={String(workout.totalSets)} />
          <Total label={t("workouts.reps")} value={String(workout.totalReps)} />
          <Total label="Volume" value={volume(workout.totalVolumeKg)} />
        </Card>

        {workout.notes ? (
          <Text variant="body" tone="secondary">
            {workout.notes}
          </Text>
        ) : null}

        {workout.exercises.map((exercise) => (
          <Card key={exercise.id} style={styles.exercise}>
            <Text variant="h3" numberOfLines={1}>
              {exercise.exerciseName ?? "Exercise"}
            </Text>
            {exercise.sets
              // Only what was actually performed. An untouched row was somewhere to type.
              .filter((set) => set.isCompleted)
              .map((set) => (
                <View key={set.id} style={styles.setRow}>
                  <Text variant="caption" tone="muted" style={styles.setNumber} tabular>
                    {set.setNumber}
                  </Text>
                  <Text variant="caption" tabular>
                    {describeSet(set.weightKg, set.reps)}
                  </Text>
                </View>
              ))}
          </Card>
        ))}
      </ScrollView>
    </Screen>
  );
}

function Total({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.total}>
      <Text variant="h3" tabular>
        {value}
      </Text>
      <Text variant="caption" tone="muted">
        {label}
      </Text>
    </View>
  );
}

function describeSet(weightKg: string | null, reps: number | null): string {
  const weight = weightKg === null ? null : Number(weightKg);
  const trimmed =
    weight === null || !Number.isFinite(weight)
      ? null
      : Number.isInteger(weight)
        ? String(weight)
        : weight.toFixed(1);

  if (trimmed !== null && reps !== null) return `${trimmed} kg × ${reps}`;
  if (reps !== null) return `${reps} reps`;
  return "—";
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  close: { paddingVertical: space.sm },
  grow: { flex: 1 },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  totals: { flexDirection: "row", justifyContent: "space-around" },
  total: { alignItems: "center", gap: 2 },
  exercise: { gap: space.xs },
  setRow: { flexDirection: "row", alignItems: "center", gap: space.md },
  setNumber: { width: 20, textAlign: "center" },
});
