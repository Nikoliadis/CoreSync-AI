import { Check } from "lucide-react-native";
import { memo, useEffect, useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { Text } from "@/components/ui/text";
import { HIT_SIZE, radius, space, type, useTheme } from "@/theme";

import { type LocalSet } from "../local-store";

type Props = {
  set: LocalSet;
  /** What the previous session did for this set number, if anything. */
  previous?: string | null;
  onChange: (changes: { reps?: number | null; weightKg?: number | null }) => void;
  onToggle: () => void;
  onDelete: () => void;
};

/**
 * One set: number, previous, weight, reps, tick.
 *
 * The interaction budget is the point. Two taps to log a set means the fields are
 * prefilled from the last one and the tick is a single large target — no dialog, no
 * confirmation, no save button. Tapping the tick *is* the save.
 *
 * Memoised because a long session renders dozens of these and typing into one must not
 * re-render the rest.
 */
export const SetRow = memo(function SetRow({
  set,
  previous,
  onChange,
  onToggle,
  onDelete,
}: Props) {
  const theme = useTheme();

  // Local text state so a partially typed number ("8." on the way to "8.5") is not
  // parsed and reformatted underneath the user's fingers.
  const [weight, setWeight] = useState(set.weightKg?.toString() ?? "");
  const [reps, setReps] = useState(set.reps?.toString() ?? "");

  useEffect(() => {
    // Re-sync when the row is prefilled from elsewhere, e.g. the set was carried
    // forward from the previous one.
    setWeight(set.weightKg?.toString() ?? "");
    setReps(set.reps?.toString() ?? "");
  }, [set.weightKg, set.reps]);

  const commit = (next: { weight?: string; reps?: string }) => {
    const weightValue = next.weight ?? weight;
    const repsValue = next.reps ?? reps;
    onChange({
      weightKg: weightValue === "" ? null : Number(weightValue.replace(",", ".")),
      reps: repsValue === "" ? null : Number(repsValue),
    });
  };

  const canComplete = reps !== "" || weight !== "";

  return (
    <View
      style={[
        styles.row,
        {
          borderColor: theme.border,
          // A completed set recedes. The one being worked on is the only one that
          // should pull the eye.
          backgroundColor: set.isCompleted ? `${theme.accent}14` : "transparent",
        },
      ]}
    >
      <Text variant="caption" tone="muted" style={styles.number} tabular>
        {set.setNumber}
      </Text>

      <Text variant="caption" tone="muted" style={styles.previous} numberOfLines={1}>
        {previous ?? "—"}
      </Text>

      <TextInput
        value={weight}
        onChangeText={(value) => {
          setWeight(value);
          commit({ weight: value });
        }}
        keyboardType="decimal-pad"
        selectTextOnFocus
        placeholder="—"
        placeholderTextColor={theme.textMuted}
        accessibilityLabel={`Weight for set ${set.setNumber}`}
        style={[styles.field, { color: theme.text, backgroundColor: theme.surfaceWell }]}
      />

      <TextInput
        value={reps}
        onChangeText={(value) => {
          setReps(value);
          commit({ reps: value });
        }}
        keyboardType="number-pad"
        selectTextOnFocus
        placeholder="—"
        placeholderTextColor={theme.textMuted}
        accessibilityLabel={`Reps for set ${set.setNumber}`}
        style={[styles.field, { color: theme.text, backgroundColor: theme.surfaceWell }]}
      />

      <Pressable
        onPress={onToggle}
        onLongPress={onDelete}
        disabled={!canComplete && !set.isCompleted}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: set.isCompleted }}
        accessibilityLabel={`Set ${set.setNumber} complete`}
        accessibilityHint="Long press to delete this set"
        style={({ pressed }) => [
          styles.tick,
          {
            backgroundColor: set.isCompleted ? theme.accent : theme.surfaceWell,
            borderColor: set.isCompleted ? theme.accent : theme.border,
            opacity: !canComplete && !set.isCompleted ? 0.4 : pressed ? 0.7 : 1,
          },
        ]}
      >
        <Check
          size={20}
          strokeWidth={3}
          color={set.isCompleted ? theme.accentInk : theme.textMuted}
        />
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    paddingVertical: space.xs,
    paddingHorizontal: space.sm,
    borderRadius: radius.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  number: { width: 20, textAlign: "center" },
  previous: { flex: 1 },
  field: {
    width: 68,
    height: HIT_SIZE,
    borderRadius: radius.sm,
    textAlign: "center",
    fontSize: type.body.fontSize,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  tick: {
    width: HIT_SIZE,
    height: HIT_SIZE,
    borderRadius: radius.sm,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: "center",
    justifyContent: "center",
  },
});
