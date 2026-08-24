import { useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useTranslate } from "@/lib/i18n";
import { space } from "@/theme";

/**
 * The screen that matters most (docs/08 §5).
 *
 * Currently the shell. The set-logging surface lands next, and it is the one place in
 * the app where every interaction budget is real: two taps to log a set, targets big
 * enough for a chalked thumb, and every write going through the offline queue so a
 * basement changes nothing about how it behaves.
 */
export default function ActiveWorkoutScreen() {
  const t = useTranslate();
  const router = useRouter();

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={styles.body}>
        <Text variant="h1">{t("workouts.active")}</Text>
        <Text variant="body" tone="secondary">
          {t("workouts.addExercise")}
        </Text>
      </View>
      <Button label={t("common.done")} variant="ghost" onPress={() => router.back()} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  body: { flex: 1, justifyContent: "center", gap: space.md },
});
