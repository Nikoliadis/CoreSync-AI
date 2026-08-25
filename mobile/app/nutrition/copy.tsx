import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Pressable, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { MEAL_LABEL_KEYS, MEAL_ORDER, type MealType } from "@/features/nutrition/api";
import { friendlyDate, localToday, shiftDate } from "@/features/nutrition/dates";
import { useDiary } from "@/features/nutrition/use-diary";
import { useTranslate, type MessageKey } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * Copy a previous day onto this one.
 *
 * People eat the same breakfast most days, and re-logging it item by item is the
 * friction that decides whether a diary survives its second week.
 *
 * The last seven days only. Copying from three months ago is not something anyone does,
 * and an unbounded date picker is a worse way to choose "yesterday".
 */
export default function CopyDayScreen() {
  const t = useTranslate();
  const router = useRouter();
  const params = useLocalSearchParams<{ date?: string }>();
  const target = params.date ?? localToday();

  const view = useDiary(target);
  const [source, setSource] = useState(() => shiftDate(target, -1));
  const [meal, setMeal] = useState<MealType | null>(null);
  const [busy, setBusy] = useState(false);

  const candidates = Array.from({ length: 7 }, (_, offset) =>
    shiftDate(target, -(offset + 1)),
  );

  const onCopy = () => {
    setBusy(true);
    void view
      .copyFrom(source, meal ?? undefined)
      .then((copied) => {
        Alert.alert(
          "Copied",
          `${copied} ${copied === 1 ? "entry" : "entries"} added to ${friendlyDate(target).toLowerCase()}.`,
        );
        router.back();
      })
      .catch(() => {
        // The server refuses an empty source day, which is the common case here —
        // somebody picking a day they did not log.
        Alert.alert("Nothing to copy", "There was nothing logged on that day.");
      })
      .finally(() => setBusy(false));
  };

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={styles.body}>
        <Text variant="h1">Copy a day</Text>
        <Text variant="body" tone="secondary">
          Onto {friendlyDate(target).toLowerCase()}.
        </Text>

        <Text variant="overline" tone="muted">
          COPY FROM
        </Text>
        <View style={styles.chips}>
          {candidates.map((iso) => (
            <Chip key={iso} active={source === iso} onPress={() => setSource(iso)}>
              {friendlyDate(iso)}
            </Chip>
          ))}
        </View>

        <Text variant="overline" tone="muted">
          WHAT
        </Text>
        <View style={styles.chips}>
          <Chip active={meal === null} onPress={() => setMeal(null)}>
            Whole day
          </Chip>
          {MEAL_ORDER.map((option) => (
            <Chip
              key={option}
              active={meal === option}
              onPress={() => setMeal(option)}
            >
              {t(MEAL_LABEL_KEYS[option] as MessageKey)}
            </Chip>
          ))}
        </View>

        <Text variant="caption" tone="muted">
          The numbers are copied exactly as they were logged, not recalculated. What you
          ate on a past day is a fact about that day.
        </Text>
      </View>

      <View style={styles.actions}>
        <Button label={t("common.cancel")} variant="ghost" onPress={() => router.back()} />
        <Button label={busy ? "Copying…" : "Copy"} disabled={busy} onPress={onCopy} />
      </View>
    </Screen>
  );
}

function Chip({
  active,
  onPress,
  children,
}: {
  active: boolean;
  onPress: () => void;
  children: React.ReactNode;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      style={[
        styles.chip,
        {
          borderColor: active ? theme.accent : theme.border,
          backgroundColor: active ? `${theme.accent}1a` : "transparent",
        },
      ]}
    >
      <Text variant="caption" tone={active ? "default" : "secondary"}>
        {children}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  body: { flex: 1, gap: space.md, paddingTop: space.lg },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: space.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  actions: { gap: space.sm, paddingBottom: space.lg },
});
