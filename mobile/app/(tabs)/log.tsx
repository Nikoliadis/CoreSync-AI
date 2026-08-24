import { useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useTranslate } from "@/lib/i18n";
import { space } from "@/theme";

/**
 * The centre tab is an action sheet, not a destination.
 *
 * Everything here is one tap from the tab bar, because these are the two things people
 * open the app to do and burying either behind a screen is how logging stops happening.
 */
export default function LogScreen() {
  const t = useTranslate();
  const router = useRouter();

  return (
    <Screen edges={["top"]}>
      <View style={styles.body}>
        <Text variant="h1">{t("tabs.log")}</Text>
        <Button
          label={t("workouts.start")}
          onPress={() => router.push("/workout/active")}
        />
        <Button
          label={t("nutrition.addFood")}
          variant="secondary"
          onPress={() => router.push("/(tabs)/nutrition")}
        />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  body: { flex: 1, justifyContent: "center", gap: space.md },
});
