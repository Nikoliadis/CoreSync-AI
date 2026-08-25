import * as Haptics from "expo-haptics";
import { useFocusEffect, useRouter } from "expo-router";
import { X } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, FlatList, Pressable, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { usePickedExercise } from "@/features/exercises/picked-exercise";
import { SetRow } from "@/features/workouts/components/set-row";
import {
  completedSetCount,
  getActiveSession,
  lastCompletedSet,
  type LocalExercise,
  type LocalSession,
  newSession,
  sessionVolume,
} from "@/features/workouts/local-store";
import {
  addExercise,
  addSet,
  completeSession,
  completeSet,
  deleteSet,
  discardSession,
  startSession,
  uncompleteSet,
  updateSet,
} from "@/features/workouts/mutations";
import {
  DEFAULT_REST_SECONDS,
  formatRest,
  useRestTimer,
} from "@/features/workouts/use-rest-timer";
import { useTranslate } from "@/lib/i18n";
import { flush } from "@/offline/sync-engine";
import { space, useTheme } from "@/theme";

/**
 * The screen that matters most (docs/08 §5).
 *
 * Everything here reads from and writes to SQLite. There is no loading state tied to the
 * network and no error state for a failed request, because no interaction on this screen
 * makes one — the queue does that afterwards. A user can complete an entire workout in a
 * basement and never see a difference.
 */
export default function ActiveWorkoutScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const rest = useRestTimer();
  const consumePicked = usePickedExercise((state) => state.consume);

  const [session, setSession] = useState<LocalSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        // Recovery is not a feature here, it is the default. The session was never held
        // in memory alone, so an app killed between sets comes back where it was.
        const existing = await getActiveSession();
        setSession(
          existing?.session ?? (await startSession(newSession({ name: "Workout" }))),
        );
      } catch (error) {
        // Leaving `session` null renders the error state rather than a spinner that
        // never resolves. An unhandled rejection here would strand the user on
        // "Loading" with no way out but force-quitting.
        console.warn("could not open a workout", error);
        setFailed(true);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const apply = useCallback(
    (operation: (current: LocalSession) => Promise<LocalSession>) => {
      setSession((current) => {
        if (!current) return current;
        // Optimistic by construction: the mutation has already persisted before the
        // promise settles, so the UI never waits on anything.
        void operation(current).then(setSession);
        return current;
      });
    },
    [],
  );

  // The picker hands its choice back through a one-slot store and this consumes it on
  // focus. `consume` clears as it reads, so returning to this screen for any other
  // reason cannot re-apply the last pick.
  useFocusEffect(
    useCallback(() => {
      const picked = consumePicked();
      if (!picked) return;
      void apply((current) =>
        addExercise(current, {
          exerciseId: picked.id,
          exerciseName: picked.name,
        }),
      );
    }, [apply, consumePicked]),
  );

  const onToggle = useCallback(
    (exercise: LocalExercise, setId: string, isCompleted: boolean) => {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      if (isCompleted) {
        void apply((current) => uncompleteSet(current, exercise.id, setId));
        return;
      }
      void apply((current) => completeSet(current, exercise.id, setId));
      rest.start(exercise.restSeconds ?? DEFAULT_REST_SECONDS);
    },
    [apply, rest],
  );

  const onFinish = useCallback(async () => {
    if (!session) return;
    const finished = await completeSession(session);
    setSession(finished);
    // Opportunistic: if there is signal the workout is already on the server by the
    // time the user is back in the car. If not, nothing here changes.
    void flush();
    router.back();
  }, [router, session]);

  const onCancel = useCallback(() => {
    if (!session) return;
    const logged = completedSetCount(session);

    // The only confirmation in the flow, and it exists because this is the one action
    // that destroys work. Everything else is reversible.
    if (logged === 0) {
      void discardSession(session).then(() => router.back());
      return;
    }
    Alert.alert(
      "Discard this workout?",
      `${logged} ${logged === 1 ? "set" : "sets"} will be deleted. This cannot be undone.`,
      [
        { text: t("common.cancel"), style: "cancel" },
        {
          text: t("common.delete"),
          style: "destructive",
          onPress: () => void discardSession(session).then(() => router.back()),
        },
      ],
    );
  }, [router, session, t]);

  if (loading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <Text tone="muted">{t("common.loading")}</Text>
        </View>
      </Screen>
    );
  }

  if (failed || !session) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Text variant="caption" tone="muted">
            {t("common.errorBody")}
          </Text>
          <Button label={t("common.cancel")} variant="ghost" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const volume = sessionVolume(session);
  const sets = completedSetCount(session);

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <View style={styles.headerText}>
          <Text variant="h2" numberOfLines={1}>
            {session.name}
          </Text>
          <Text variant="caption" tone="muted" tabular>
            {sets} {sets === 1 ? "set" : "sets"} · {volume} kg
          </Text>
        </View>
        <Button
          label={t("workouts.finish")}
          size="sm"
          onPress={() => void onFinish()}
          disabled={sets === 0}
        />
      </View>

      {rest.isResting && rest.remaining !== null && (
        <View style={[styles.rest, { backgroundColor: theme.surfaceWell }]}>
          <Text variant="h3" tone="accent" tabular>
            {t("workouts.restTimer", { seconds: formatRest(rest.remaining) })}
          </Text>
          <View style={styles.restActions}>
            <Text
              variant="caption"
              tone="secondary"
              onPress={() => rest.add(30)}
              accessibilityRole="button"
              style={styles.restAction}
            >
              +30s
            </Text>
            <Text
              variant="caption"
              tone="secondary"
              onPress={rest.skip}
              accessibilityRole="button"
              style={styles.restAction}
            >
              {t("common.done")}
            </Text>
          </View>
        </View>
      )}

      <FlatList
        data={session.exercises}
        keyExtractor={(exercise) => exercise.id}
        contentContainerStyle={styles.list}
        // A long session is dozens of rows; keeping the window small is what stops
        // scrolling stuttering on a mid-range Android.
        initialNumToRender={4}
        windowSize={7}
        removeClippedSubviews
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={
          <Card style={styles.empty}>
            <Text tone="secondary">{t("workouts.addExercise")}</Text>
          </Card>
        }
        renderItem={({ item: exercise }) => (
          <Card style={styles.exercise}>
            <Text variant="h3">{exercise.exerciseName}</Text>

            <View style={styles.columns}>
              <Text variant="overline" tone="muted" style={styles.colNumber}>
                #
              </Text>
              <Text variant="overline" tone="muted" style={styles.colPrevious}>
                PREV
              </Text>
              <Text variant="overline" tone="muted" style={styles.colField}>
                KG
              </Text>
              <Text variant="overline" tone="muted" style={styles.colField}>
                REPS
              </Text>
              <View style={styles.colTick} />
            </View>

            {exercise.sets.map((set) => (
              <SetRow
                key={set.id}
                set={set}
                previous={
                  set.weightKg && set.reps ? `${set.weightKg} × ${set.reps}` : null
                }
                onChange={(changes) =>
                  void apply((current) => updateSet(current, exercise.id, set.id, changes))
                }
                onToggle={() => onToggle(exercise, set.id, set.isCompleted)}
                onDelete={() =>
                  void apply((current) => deleteSet(current, exercise.id, set.id))
                }
              />
            ))}

            <Text
              accessibilityRole="button"
              variant="caption"
              tone="accent"
              style={styles.addSet}
              onPress={() => {
                // Carried forward from the last completed set: weight rarely changes
                // between sets, and retyping it is the most repeated waste in the app.
                const previous = lastCompletedSet(exercise);
                void apply((current) =>
                  addSet(current, exercise.id, {
                    weightKg: previous?.weightKg ?? null,
                    reps: previous?.reps ?? null,
                  }),
                );
              }}
            >
              + {t("workouts.sets")}
            </Text>
          </Card>
        )}
      />

      <View style={[styles.footer, { borderTopColor: theme.border }]}>
        <Button
          label={t("workouts.addExercise")}
          variant="secondary"
          style={styles.grow}
          onPress={() => router.push("/workout/exercise-picker")}
        />
        <Pressable
          onPress={onCancel}
          accessibilityRole="button"
          accessibilityLabel={t("common.cancel")}
          style={({ pressed }) => [
            styles.cancel,
            { borderColor: theme.border, opacity: pressed ? 0.7 : 1 },
          ]}
        >
          <X size={20} color={theme.textMuted} />
        </Pressable>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  headerText: { flex: 1, gap: 2 },
  rest: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  restActions: { flexDirection: "row", gap: space.lg },
  restAction: { paddingVertical: space.sm, paddingHorizontal: space.sm },
  list: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  empty: { alignItems: "center", paddingVertical: space.xl },
  exercise: { gap: space.xs },
  columns: { flexDirection: "row", gap: space.sm, paddingHorizontal: space.sm },
  colNumber: { width: 20, textAlign: "center" },
  colPrevious: { flex: 1 },
  colField: { width: 68, textAlign: "center" },
  colTick: { width: 44 },
  addSet: { paddingVertical: space.md, textAlign: "center" },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    padding: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  grow: { flex: 1 },
  cancel: {
    width: 52,
    height: 52,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
  },
});
