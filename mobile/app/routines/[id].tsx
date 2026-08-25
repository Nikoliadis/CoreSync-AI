import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Copy, Pencil, Trash2 } from "lucide-react-native";
import { useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { prescription, routineKeys, routinesApi } from "@/features/routines/api";
import { getActiveSession } from "@/features/workouts/local-store";
import { startRoutineSession } from "@/features/workouts/mutations";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

/**
 * One routine: what it prescribes, and the button that turns it into a workout.
 *
 * The plan is read-only here. Editing is a separate screen because the two are different
 * activities — you read this one standing at a rack, and edit at a desk — and mixing them
 * puts destructive controls under a thumb that is trying to start a set.
 */
export default function RoutineDetailScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();

  const [starting, setStarting] = useState(false);

  const routine = useQuery({
    queryKey: routineKeys.detail(id),
    queryFn: () => routinesApi.get(id),
    enabled: Boolean(id),
  });

  const onStart = async () => {
    const plan = routine.data;
    if (!plan || starting) return;

    setStarting(true);
    try {
      // One workout at a time — the server enforces it too, and finding out here means a
      // clear question rather than a 409 after the session was already built locally.
      const active = await getActiveSession();
      if (active) {
        Alert.alert(
          "A workout is already in progress",
          "Finish or discard it before starting another.",
          [
            { text: t("common.cancel"), style: "cancel" },
            { text: t("workouts.resume"), onPress: () => router.push("/workout/active") },
          ],
        );
        return;
      }

      await startRoutineSession(plan);
      router.replace("/workout/active");
    } catch (error) {
      console.warn("could not start from routine", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setStarting(false);
    }
  };

  const onDuplicate = async () => {
    if (!routine.data) return;
    try {
      const copy = await routinesApi.duplicate(routine.data.id);
      await queryClient.invalidateQueries({ queryKey: routineKeys.all });
      router.replace(`/routines/${copy.id}`);
    } catch (error) {
      console.warn("could not duplicate routine", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    }
  };

  const onDelete = () => {
    if (!routine.data) return;
    Alert.alert(t("workouts.deleteRoutine"), `"${routine.data.name}" will be removed.`, [
      { text: t("common.cancel"), style: "cancel" },
      {
        text: t("common.delete"),
        style: "destructive",
        onPress: () => {
          void (async () => {
            try {
              await routinesApi.remove(routine.data.id);
              await queryClient.invalidateQueries({ queryKey: routineKeys.all });
              router.back();
            } catch (error) {
              console.warn("could not delete routine", error);
              Alert.alert(t("common.errorTitle"), t("common.errorBody"));
            }
          })();
        },
      },
    ]);
  };

  if (routine.isLoading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  if (routine.isError || !routine.data) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button label={t("common.retry")} variant="ghost" onPress={() => void routine.refetch()} />
          <Button label={t("common.cancel")} variant="ghost" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const plan = routine.data;

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text variant="h1" numberOfLines={2} style={styles.grow}>
            {plan.name}
          </Text>
          <IconAction label={t("workouts.editRoutine")} onPress={() => router.push(`/routines/edit?id=${plan.id}`)}>
            <Pencil size={18} color={theme.textMuted} />
          </IconAction>
          <IconAction label={t("workouts.duplicate")} onPress={() => void onDuplicate()}>
            <Copy size={18} color={theme.textMuted} />
          </IconAction>
          <IconAction label={t("workouts.deleteRoutine")} onPress={onDelete}>
            <Trash2 size={18} color={theme.textMuted} />
          </IconAction>
        </View>

        <Text variant="caption" tone="muted">
          {t("workouts.exerciseCount", { count: plan.exercises.length })} ·{" "}
          {t("workouts.setCount", { count: plan.totalSets })}
          {plan.estimatedMinutes ? ` · ~${plan.estimatedMinutes} min` : ""}
        </Text>

        {plan.notes ? (
          <Text variant="body" tone="secondary">
            {plan.notes}
          </Text>
        ) : null}

        {plan.exercises.map((exercise) => (
          <Card key={exercise.id} style={styles.exercise}>
            <Text variant="h3" numberOfLines={1}>
              {exercise.exerciseName ?? "Exercise"}
            </Text>
            <Text variant="caption" tone="muted" tabular>
              {prescription(exercise.sets)}
              {exercise.restSeconds ? ` · ${exercise.restSeconds}s rest` : ""}
            </Text>
            {exercise.notes ? (
              <Text variant="caption" tone="secondary">
                {exercise.notes}
              </Text>
            ) : null}
          </Card>
        ))}
      </ScrollView>

      <View style={[styles.footer, { borderTopColor: theme.border }]}>
        <Button
          label={starting ? t("common.loading") : t("workouts.startRoutine")}
          disabled={starting || plan.exercises.length === 0}
          style={styles.grow}
          onPress={() => void onStart()}
        />
      </View>
    </Screen>
  );
}

function IconAction({
  label,
  onPress,
  children,
}: {
  label: string;
  onPress: () => void;
  children: React.ReactNode;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={8}
      style={({ pressed }) => [styles.iconAction, { opacity: pressed ? 0.6 : 1 }]}
    >
      {children}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  header: { flexDirection: "row", alignItems: "center", gap: space.xs },
  iconAction: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  exercise: { gap: space.xs },
  grow: { flex: 1 },
  footer: {
    flexDirection: "row",
    padding: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
});
