import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { ChevronDown, ChevronUp, Minus, Plus, Trash2 } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { usePickedExercise } from "@/features/exercises/picked-exercise";
import { type RoutineExerciseInput, routineKeys, routinesApi } from "@/features/routines/api";
import { useTranslate } from "@/lib/i18n";
import { HIT_SIZE, radius, space, type, useTheme } from "@/theme";

/**
 * Build or change a routine.
 *
 * One screen for both, because "create" and "edit" differ only in whether there is
 * already something to load. Held entirely in local state and saved in one go: a routine
 * half-written is not a routine, and autosaving each keystroke would put a stream of
 * versions on the server for a document nobody has finished writing.
 *
 * Exercises are chosen through the same picker the active workout uses. A second picker
 * would be a second place for the catalogue to be wrong.
 */

type DraftExercise = {
  /** Local only. The server mints real ids on save. */
  key: string;
  exerciseId: string;
  exerciseName: string;
  setCount: number;
  repsMin: string;
  repsMax: string;
};

export default function RoutineEditScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const isEditing = Boolean(id);

  const consumePicked = usePickedExercise((state) => state.consume);

  const [name, setName] = useState("");
  const [exercises, setExercises] = useState<DraftExercise[]>([]);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(!isEditing);

  const existing = useQuery({
    queryKey: routineKeys.detail(id ?? ""),
    queryFn: () => routinesApi.get(id ?? ""),
    enabled: isEditing,
  });

  useEffect(() => {
    if (!existing.data || loaded) return;
    setName(existing.data.name);
    setExercises(
      existing.data.exercises.map((exercise) => ({
        key: exercise.id,
        exerciseId: exercise.exerciseId,
        exerciseName: exercise.exerciseName ?? "Exercise",
        setCount: exercise.sets.length || 1,
        repsMin: exercise.sets[0]?.targetRepsMin?.toString() ?? "",
        repsMax: exercise.sets[0]?.targetRepsMax?.toString() ?? "",
      })),
    );
    // Only once. Re-running on every refetch would throw away edits in progress.
    setLoaded(true);
  }, [existing.data, loaded]);

  // The picker hands its choice back through a one-slot store, cleared as it is read.
  useFocusEffect(
    useCallback(() => {
      const picked = consumePicked();
      if (!picked) return;
      setExercises((current) => [
        ...current,
        {
          key: `${picked.id}-${String(current.length)}-${String(Date.now())}`,
          exerciseId: picked.id,
          exerciseName: picked.name,
          setCount: 3,
          repsMin: "8",
          repsMax: "12",
        },
      ]);
    }, [consumePicked]),
  );

  const update = (key: string, changes: Partial<DraftExercise>) =>
    setExercises((current) =>
      current.map((exercise) => (exercise.key === key ? { ...exercise, ...changes } : exercise)),
    );

  const move = (key: string, direction: -1 | 1) =>
    setExercises((current) => {
      const from = current.findIndex((exercise) => exercise.key === key);
      const to = from + direction;
      if (from === -1 || to < 0 || to >= current.length) return current;

      const next = [...current];
      const [moved] = next.splice(from, 1);
      if (!moved) return current;
      next.splice(to, 0, moved);
      return next;
    });

  const onSave = async () => {
    const trimmed = name.trim();
    if (!trimmed || exercises.length === 0 || saving) return;

    const payload: RoutineExerciseInput[] = exercises.map((exercise) => ({
      exerciseId: exercise.exerciseId,
      sets: Array.from({ length: exercise.setCount }, () => ({
        targetRepsMin: numeric(exercise.repsMin),
        targetRepsMax: numeric(exercise.repsMax),
      })),
    }));

    setSaving(true);
    try {
      if (isEditing && id) {
        // Two calls because the API separates metadata from contents. The version goes
        // with the metadata so a conflicting edit from another device is reported rather
        // than silently overwritten.
        await routinesApi.update(id, { name: trimmed, version: existing.data?.version });
        await routinesApi.replaceExercises(id, payload);
      } else {
        const created = await routinesApi.create({ name: trimmed, exercises: payload });
        await queryClient.invalidateQueries({ queryKey: routineKeys.all });
        router.replace(`/routines/${created.id}`);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: routineKeys.all });
      router.back();
    } catch (error) {
      console.warn("could not save routine", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setSaving(false);
    }
  };

  if (isEditing && existing.isLoading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  const canSave = name.trim().length > 0 && exercises.length > 0 && !saving;

  return (
    <Screen edges={["top"]} padded={false}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.grow}
      >
        <View style={[styles.header, { borderBottomColor: theme.border }]}>
          <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.cancel}>
            <Text tone="accent">{t("common.cancel")}</Text>
          </Pressable>
          <Text variant="h3" style={styles.title} numberOfLines={1}>
            {isEditing ? t("workouts.editRoutine") : t("workouts.newRoutine")}
          </Text>
          <Pressable
            onPress={() => void onSave()}
            disabled={!canSave}
            accessibilityRole="button"
            accessibilityState={{ disabled: !canSave }}
            style={styles.cancel}
          >
            <Text tone={canSave ? "accent" : "muted"}>{t("common.save")}</Text>
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder={t("workouts.routineName")}
            placeholderTextColor={theme.textMuted}
            accessibilityLabel={t("workouts.routineName")}
            style={[styles.nameField, { color: theme.text, backgroundColor: theme.surfaceWell }]}
          />

          {exercises.map((exercise, index) => (
            <Card key={exercise.key} style={styles.exercise}>
              <View style={styles.exerciseHeader}>
                <Text variant="h3" numberOfLines={1} style={styles.grow}>
                  {exercise.exerciseName}
                </Text>
                <IconAction
                  label={`Move ${exercise.exerciseName} up`}
                  disabled={index === 0}
                  onPress={() => move(exercise.key, -1)}
                >
                  <ChevronUp size={18} color={theme.textMuted} />
                </IconAction>
                <IconAction
                  label={`Move ${exercise.exerciseName} down`}
                  disabled={index === exercises.length - 1}
                  onPress={() => move(exercise.key, 1)}
                >
                  <ChevronDown size={18} color={theme.textMuted} />
                </IconAction>
                <IconAction
                  label={`Remove ${exercise.exerciseName}`}
                  onPress={() =>
                    setExercises((current) =>
                      current.filter((item) => item.key !== exercise.key),
                    )
                  }
                >
                  <Trash2 size={18} color={theme.textMuted} />
                </IconAction>
              </View>

              <View style={styles.row}>
                <Text variant="caption" tone="muted" style={styles.rowLabel}>
                  {t("workouts.sets")}
                </Text>
                <IconAction
                  label={t("active.oneFewerSet")}
                  disabled={exercise.setCount <= 1}
                  onPress={() => update(exercise.key, { setCount: exercise.setCount - 1 })}
                >
                  <Minus size={16} color={theme.textMuted} />
                </IconAction>
                <Text tabular style={styles.setCount}>
                  {exercise.setCount}
                </Text>
                <IconAction
                  label={t("active.oneMoreSet")}
                  disabled={exercise.setCount >= 30}
                  onPress={() => update(exercise.key, { setCount: exercise.setCount + 1 })}
                >
                  <Plus size={16} color={theme.textMuted} />
                </IconAction>
              </View>

              <View style={styles.row}>
                <Text variant="caption" tone="muted" style={styles.rowLabel}>
                  {t("workouts.reps")}
                </Text>
                <TextInput
                  value={exercise.repsMin}
                  onChangeText={(value) => update(exercise.key, { repsMin: value })}
                  keyboardType="number-pad"
                  selectTextOnFocus
                  placeholder="—"
                  placeholderTextColor={theme.textMuted}
                  accessibilityLabel={`Minimum reps for ${exercise.exerciseName}`}
                  style={[styles.repField, { color: theme.text, backgroundColor: theme.surfaceWell }]}
                />
                <Text tone="muted">–</Text>
                <TextInput
                  value={exercise.repsMax}
                  onChangeText={(value) => update(exercise.key, { repsMax: value })}
                  keyboardType="number-pad"
                  selectTextOnFocus
                  placeholder="—"
                  placeholderTextColor={theme.textMuted}
                  accessibilityLabel={`Maximum reps for ${exercise.exerciseName}`}
                  style={[styles.repField, { color: theme.text, backgroundColor: theme.surfaceWell }]}
                />
              </View>
            </Card>
          ))}

          <Button
            label={t("workouts.addExercise")}
            variant="secondary"
            onPress={() => router.push("/workout/exercise-picker")}
          />
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
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
      style={({ pressed }) => [
        styles.iconAction,
        { opacity: disabled ? 0.25 : pressed ? 0.6 : 1 },
      ]}
    >
      {children}
    </Pressable>
  );
}

/** Blank means unprescribed, which is a real choice — not zero. */
function numeric(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null;
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: { flex: 1, textAlign: "center" },
  cancel: { minWidth: 64, paddingVertical: space.sm },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  grow: { flex: 1 },
  nameField: {
    height: HIT_SIZE,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    fontSize: type.body.fontSize,
    fontWeight: "600",
  },
  exercise: { gap: space.sm },
  exerciseHeader: { flexDirection: "row", alignItems: "center", gap: space.xs },
  iconAction: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  rowLabel: { flex: 1 },
  setCount: { minWidth: 28, textAlign: "center" },
  repField: {
    width: 56,
    height: 40,
    borderRadius: radius.sm,
    textAlign: "center",
    fontSize: type.body.fontSize,
    fontVariant: ["tabular-nums"],
  },
});
