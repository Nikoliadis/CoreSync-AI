import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Check } from "lucide-react-native";
import { useEffect, useState } from "react";
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
import {
  GOAL_BLURBS,
  GOAL_LABELS,
  GOAL_TYPES,
  type GoalType,
  goalKeys,
  goalsApi,
  macroSplit,
  rateWarning,
  signedWeeklyRate,
} from "@/features/goals/api";
import { progressApi, progressKeys } from "@/features/progress/api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, type, useTheme } from "@/theme";

/**
 * What you are training for, and the daily numbers that follow from it.
 *
 * Setting a goal and recalculating targets are two server calls, run in sequence, because
 * they are genuinely two things: the goal is the intent, the targets are arithmetic over
 * it. Doing only the first would leave somebody with a stated goal and yesterday's
 * calories, which is the kind of quiet mismatch nobody notices until the plan has failed.
 */
export default function GoalsScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const me = useQuery({ queryKey: goalKeys.me(), queryFn: goalsApi.me });
  const weight = useQuery({
    queryKey: progressKeys.weight(30),
    queryFn: () => progressApi.weight(30),
  });

  const [goalType, setGoalType] = useState<GoalType>("maintain");
  const [targetWeight, setTargetWeight] = useState("");
  const [rate, setRate] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!me.data || loaded) return;
    const goal = me.data.goal;
    if (goal) {
      setGoalType(goal.goalType);
      setTargetWeight(goal.targetWeightKg ? Number(goal.targetWeightKg).toFixed(1) : "");
      setRate(goal.weeklyRateKg ? Math.abs(Number(goal.weeklyRateKg)).toFixed(2) : "");
    }
    // Once only: re-running on refetch would discard edits in progress.
    setLoaded(true);
  }, [me.data, loaded]);

  const currentWeight = weight.data?.latestTrendKg ?? weight.data?.latestWeightKg ?? null;
  const parsedRate = rate.trim() === "" ? null : Number(rate.replace(",", "."));
  const warning = rateWarning(
    goalType,
    Number.isFinite(parsedRate) ? parsedRate : null,
    currentWeight === null ? null : Number(currentWeight),
  );

  const needsDestination = goalType !== "maintain" && goalType !== "performance";
  const targets = macroSplit(me.data?.targets ?? null);

  const onSave = async () => {
    if (saving) return;
    const parsedWeight = targetWeight.trim() === "" ? null : Number(targetWeight.replace(",", "."));
    if (parsedWeight !== null && (!Number.isFinite(parsedWeight) || parsedWeight <= 0)) {
      Alert.alert("Check that weight", "Target weight is not a number.");
      return;
    }

    setSaving(true);
    try {
      await goalsApi.setGoal({
        goalType,
        targetWeightKg: parsedWeight,
        weeklyRateKg: signedWeeklyRate(goalType, parsedRate),
      });

      const calculation = await goalsApi.recalculateTargets();
      await queryClient.invalidateQueries({ queryKey: goalKeys.all });

      if (calculation.wasClampedToFloor) {
        // Said out loud. The app just gave different numbers than were asked for, and
        // discovering that silently is how people conclude the maths is broken.
        Alert.alert(
          "Targets raised to a safe floor",
          "The deficit you asked for fell below the minimum we will set, so your calories " +
            "were raised. Aim for a slower rate if you want the deficit you had in mind.",
        );
      }
    } catch (error) {
      console.warn("could not save goal", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setSaving(false);
    }
  };

  if (me.isLoading) {
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
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.grow}
      >
        <View style={[styles.header, { borderBottomColor: theme.border }]}>
          <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.action}>
            <Text tone="accent">{t("common.cancel")}</Text>
          </Pressable>
          <Text variant="h3" style={styles.title}>
            Goal
          </Text>
          <View style={styles.action} />
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.options}>
            {GOAL_TYPES.map((option) => (
              <Pressable
                key={option}
                onPress={() => setGoalType(option)}
                accessibilityRole="radio"
                accessibilityState={{ selected: goalType === option }}
                style={[
                  styles.option,
                  {
                    borderColor: goalType === option ? theme.accent : theme.border,
                    backgroundColor: goalType === option ? `${theme.accent}12` : "transparent",
                  },
                ]}
              >
                <View style={styles.optionText}>
                  <Text variant="body">{GOAL_LABELS[option]}</Text>
                  <Text variant="caption" tone="muted">
                    {GOAL_BLURBS[option]}
                  </Text>
                </View>
                {goalType === option && <Check size={18} color={theme.accentText} />}
              </Pressable>
            ))}
          </View>

          {needsDestination && (
            <Card style={styles.card}>
              <View style={styles.row}>
                <Text variant="body" style={styles.grow}>
                  Target weight
                </Text>
                <TextInput
                  value={targetWeight}
                  onChangeText={setTargetWeight}
                  keyboardType="decimal-pad"
                  selectTextOnFocus
                  placeholder={currentWeight ? Number(currentWeight).toFixed(1) : "—"}
                  placeholderTextColor={theme.textMuted}
                  accessibilityLabel="Target weight in kilograms"
                  style={[styles.field, { color: theme.text, backgroundColor: theme.surfaceWell }]}
                />
                <Text variant="caption" tone="muted" style={styles.unit}>
                  kg
                </Text>
              </View>

              <View style={styles.row}>
                <Text variant="body" style={styles.grow}>
                  Weekly rate
                </Text>
                <TextInput
                  value={rate}
                  onChangeText={setRate}
                  keyboardType="decimal-pad"
                  selectTextOnFocus
                  placeholder="0.50"
                  placeholderTextColor={theme.textMuted}
                  accessibilityLabel="Weekly rate in kilograms"
                  style={[styles.field, { color: theme.text, backgroundColor: theme.surfaceWell }]}
                />
                <Text variant="caption" tone="muted" style={styles.unit}>
                  kg
                </Text>
              </View>

              {warning && (
                <Text variant="caption" tone="secondary">
                  {warning}
                </Text>
              )}
            </Card>
          )}

          {targets && (
            <Card style={styles.card}>
              <Text variant="overline" tone="muted">
                CURRENT DAILY TARGETS
              </Text>
              <View style={styles.targets}>
                <Target label="kcal" value={targets.calories} />
                <Target label="protein" value={targets.protein} />
                <Target label="carbs" value={targets.carbs} />
                <Target label="fat" value={targets.fat} />
              </View>
              {me.data?.targets?.rationale ? (
                <Text variant="caption" tone="muted">
                  {me.data.targets.rationale}
                </Text>
              ) : null}
            </Card>
          )}

          <Button
            label={saving ? t("common.loading") : "Save goal and recalculate"}
            disabled={saving}
            onPress={() => void onSave()}
          />

          <Text variant="caption" tone="muted">
            Saving recalculates your daily targets from your profile, current weight and
            this goal.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

function Target({ label, value }: { label: string; value: number }) {
  return (
    <View style={styles.target}>
      <Text variant="h3" tabular>
        {value}
      </Text>
      <Text variant="caption" tone="muted">
        {label}
      </Text>
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
  title: { flex: 1, textAlign: "center" },
  action: { minWidth: 64, paddingVertical: space.sm },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  grow: { flex: 1 },
  options: { gap: space.sm },
  option: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    padding: space.md,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  optionText: { flex: 1, gap: 2 },
  card: { gap: space.sm },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  field: {
    width: 84,
    height: 40,
    borderRadius: radius.sm,
    textAlign: "center",
    fontSize: type.body.fontSize,
    fontVariant: ["tabular-nums"],
  },
  unit: { width: 22 },
  targets: { flexDirection: "row", justifyContent: "space-between" },
  target: { alignItems: "center", gap: 2 },
});
