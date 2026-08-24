import { useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useTranslate } from "@/lib/i18n";
import { space } from "@/theme";

export default function WorkoutsScreen() {
  const t = useTranslate();
  const router = useRouter();

  return (
    <Screen edges={["top"]}>
      <Text variant="h1" style={styles.title}>
        {t("tabs.workouts")}
      </Text>
      <View style={styles.body}>
        <Text variant="body" tone="secondary">
          {t("workouts.noHistory")}
        </Text>
        <Button
          label={t("workouts.start")}
          style={styles.action}
          onPress={() => router.push("/workout/active")}
        />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { marginBottom: space.lg },
  body: { flex: 1, justifyContent: "center", gap: space.md },
  action: { marginTop: space.sm },
});
