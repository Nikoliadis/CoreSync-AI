import * as Haptics from "expo-haptics";
import { useFocusEffect, useRouter } from "expo-router";
import { ChevronDown, ChevronUp, Pause, Play, Trash2, X } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, FlatList, Pressable, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { usePickedExercise } from "@/features/exercises/picked-exercise";
import { SetRow } from "@/features/workouts/components/set-row";
import {
  formatPrevious,
  previousSet,
  recordSetId,
} from "@/features/workouts/history-api";
import {
  completedSetCount,
  elapsedSeconds,
  formatElapsed,
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
  moveExercise,
  pauseSession,
  removeExercise,
  resumeSession,
  startSession,
  uncompleteSet,
  updateSet,
} from "@/features/workouts/mutations";
import { useExerciseHistory } from "@/features/workouts/use-exercise-history";
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
  const now = useTicker(session?.pausedAt == null && session?.completedAt == null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  // The session as of the last applied mutation. A ref rather than the state value
  // because `apply` must see what the previous operation produced, not what the render
  // it was created in closed over.
  const latest = useRef<LocalSession | null>(null);
  const chain = useRef<Promise<void>>(Promise.resolve());

  const remember = useCallback((next: LocalSession | null) => {
    latest.current = next;
    setSession(next);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        // Recovery is not a feature here, it is the default. The session was never held
        // in memory alone, so an app killed between sets comes back where it was.
        const existing = await getActiveSession();
        remember(existing?.session ?? (await startSession(newSession({ name: "Workout" }))));
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
  }, [remember]);

  /**
   * Run a mutation against the current session and adopt the result.
   *
   * Serialized through a promise chain, and deliberately outside any state updater. Two
   * things go wrong otherwise. React invokes updaters twice in development, so a mutation
   * performed inside one adds two sets, or banks a pause twice. And typing into a set row
   * fires one of these per keystroke: without the chain each reads the same starting
   * session and the last write wins, dropping the ones before it.
   *
   * Optimistic by construction — the mutation persists to SQLite before it resolves, so
   * nothing here waits on a network call.
   */
  const apply = useCallback(
    (operation: (current: LocalSession) => Promise<LocalSession>) => {
      chain.current = chain.current
        .then(async () => {
          const current = latest.current;
          if (!current) return;
          remember(await operation(current));
        })
        .catch((error: unknown) => {
          // The local write failed, which means the device storage did. Keeping the
          // chain alive matters more than this one operation: rejecting it permanently
          // would silently stop every later set from being saved.
          console.warn("workout mutation failed", error);
        });
    },
    [remember],
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
    remember(finished);
    // Opportunistic: if there is signal the workout is already on the server by the
    // time the user is back in the car. If not, nothing here changes.
    void flush();
    router.back();
  }, [remember, router, session]);

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
  const isPaused = Boolean(session.pausedAt);
  const elapsed = elapsedSeconds(session, now);

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <View style={styles.headerText}>
          <Text variant="h2" numberOfLines={1}>
            {session.name}
          </Text>
          <Text variant="caption" tone="muted" tabular>
            {formatElapsed(elapsed)} · {sets} {sets === 1 ? "set" : "sets"} · {volume} kg
          </Text>
        </View>
        <IconAction
          label={isPaused ? "Resume the workout" : "Pause the workout"}
          onPress={() =>
            void apply((current) =>
              current.pausedAt ? resumeSession(current) : pauseSession(current),
            )
          }
        >
          {isPaused ? (
            <Play size={20} color={theme.accentText} />
          ) : (
            <Pause size={20} color={theme.textMuted} />
          )}
        </IconAction>
        <Button
          label={t("workouts.finish")}
          size="sm"
          onPress={() => void onFinish()}
          disabled={sets === 0}
        />
      </View>

      {isPaused && (
        // A paused workout that looks like a running one is a trap: somebody finishes,
        // and the duration is wrong with nothing on screen to have warned them.
        <Pressable
          onPress={() => void apply((current) => resumeSession(current))}
          accessibilityRole="button"
          accessibilityLabel="Resume the workout"
          style={[styles.paused, { backgroundColor: theme.surfaceWell }]}
        >
          <Text variant="caption" tone="accent">
            Paused — tap to resume
          </Text>
        </Pressable>
      )}

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
        renderItem={({ item: exercise, index }) => (
          <ExerciseCard
            exercise={exercise}
            isFirst={index === 0}
            isLast={index === session.exercises.length - 1}
            apply={apply}
            onToggle={onToggle}
          />
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

/**
 * A clock that only ticks while it needs to.
 *
 * `Date.now()` on every tick rather than an incremented counter: the app is backgrounded
 * for most of a real session, timers there are throttled or stopped, and a counter comes
 * back minutes behind. Reading the wall clock is right however long it slept.
 *
 * Stops entirely while paused or finished, so a session left open on a bench does not
 * re-render once a second forever.
 */
function useTicker(running: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  // Read once more when it stops, so the frozen figure is the moment of the pause rather
  // than up to a second before it.
  useEffect(() => {
    if (!running) setNow(Date.now());
  }, [running]);

  return now;
}

/**
 * One exercise: its sets, what was done last time, and where it sits in the session.
 *
 * A component rather than an inline `renderItem` because each card loads its own history
 * and records, and a hook cannot live inside a render callback. It also means a card
 * whose history is still in flight does not re-render its neighbours.
 */
function ExerciseCard({
  exercise,
  isFirst,
  isLast,
  apply,
  onToggle,
}: {
  exercise: LocalExercise;
  isFirst: boolean;
  isLast: boolean;
  apply: (operation: (current: LocalSession) => Promise<LocalSession>) => void;
  onToggle: (exercise: LocalExercise, setId: string, isCompleted: boolean) => void;
}) {
  const t = useTranslate();
  const theme = useTheme();
  const { history, records } = useExerciseHistory(exercise.exerciseId);

  // One trophy per exercise, on the best set. Badging every set that beats the standing
  // record turns a progressive warm-up into a row of meaningless awards.
  const trophySetId = recordSetId(exercise.sets, records);

  const onRemove = useCallback(() => {
    const logged = exercise.sets.filter((set) => set.isCompleted).length;
    if (logged === 0) {
      // Nothing to lose. Added by mistake, taken straight back out, no dialog.
      void apply((current) => removeExercise(current, exercise.id));
      return;
    }
    Alert.alert(
      `Remove ${exercise.exerciseName}?`,
      `${logged} logged ${logged === 1 ? "set" : "sets"} will be deleted.`,
      [
        { text: t("common.cancel"), style: "cancel" },
        {
          text: t("common.delete"),
          style: "destructive",
          onPress: () => void apply((current) => removeExercise(current, exercise.id)),
        },
      ],
    );
  }, [apply, exercise, t]);

  return (
    <Card style={styles.exercise}>
      <View style={styles.exerciseHeader}>
        <Text variant="h3" numberOfLines={1} style={styles.grow}>
          {exercise.exerciseName}
        </Text>
        <IconAction
          label={`Move ${exercise.exerciseName} up`}
          disabled={isFirst}
          onPress={() => void apply((current) => moveExercise(current, exercise.id, -1))}
        >
          <ChevronUp size={18} color={theme.textMuted} />
        </IconAction>
        <IconAction
          label={`Move ${exercise.exerciseName} down`}
          disabled={isLast}
          onPress={() => void apply((current) => moveExercise(current, exercise.id, 1))}
        >
          <ChevronDown size={18} color={theme.textMuted} />
        </IconAction>
        <IconAction label={`Remove ${exercise.exerciseName}`} onPress={onRemove}>
          <Trash2 size={18} color={theme.textMuted} />
        </IconAction>
      </View>

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
          // The previous *session*, not the row's own values. Showing the latter back to
          // the user was a column that told them what they had already typed.
          previous={formatPrevious(previousSet(history, set.setNumber))}
          isRecord={set.id === trophySetId}
          onChange={(changes) =>
            void apply((current) => updateSet(current, exercise.id, set.id, changes))
          }
          onToggle={() => onToggle(exercise, set.id, set.isCompleted)}
          onDelete={() => void apply((current) => deleteSet(current, exercise.id, set.id))}
        />
      ))}

      <Text
        accessibilityRole="button"
        variant="caption"
        tone="accent"
        style={styles.addSet}
        onPress={() => {
          // Carried forward from the last completed set: weight rarely changes between
          // sets, and retyping it is the most repeated waste in the app. Falls back to
          // last session's opener so the first set of a new exercise is prefilled too.
          const previous = lastCompletedSet(exercise);
          const lastTime = previousSet(history, exercise.sets.length + 1);
          void apply((current) =>
            addSet(current, exercise.id, {
              weightKg: previous?.weightKg ?? numeric(lastTime?.weightKg),
              reps: previous?.reps ?? lastTime?.reps ?? null,
            }),
          );
        }}
      >
        + {t("workouts.sets")}
      </Text>
    </Card>
  );
}

function IconAction({
  label,
  disabled = false,
  onPress,
  children,
}: {
  label: string;
  disabled?: boolean;
  onPress: () => void;
  children: React.ReactNode;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled }}
      hitSlop={8}
      style={({ pressed }) => [styles.iconAction, { opacity: disabled ? 0.25 : pressed ? 0.6 : 1 }]}
    >
      {children}
    </Pressable>
  );
}

/** History sends decimals as strings; a set row holds numbers. */
function numeric(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
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
  paused: { alignItems: "center", paddingVertical: space.sm },
  restActions: { flexDirection: "row", gap: space.lg },
  restAction: { paddingVertical: space.sm, paddingHorizontal: space.sm },
  list: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  empty: { alignItems: "center", paddingVertical: space.xl },
  exercise: { gap: space.xs },
  exerciseHeader: { flexDirection: "row", alignItems: "center", gap: space.xs },
  iconAction: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
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
