import { useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

export default function WelcomeScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={styles.body}>
        {/* The accent used once, on the word that carries the product's intent. */}
        <View style={[styles.mark, { backgroundColor: theme.accent }]} />
        <Text variant="display">{t("auth.welcomeTitle")}</Text>
        <Text variant="body" tone="secondary" style={styles.lead}>
          {t("auth.welcomeBody")}
        </Text>
      </View>

      <View style={styles.actions}>
        <Button label={t("auth.register")} onPress={() => router.push("/(auth)/register")} />
        <Button
          label={t("auth.login")}
          variant="ghost"
          onPress={() => router.push("/(auth)/login")}
        />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  body: { flex: 1, justifyContent: "flex-end", paddingBottom: space.xxl, gap: space.md },
  mark: { width: 48, height: 6, borderRadius: 3, marginBottom: space.lg },
  lead: { maxWidth: 320 },
  actions: { gap: space.sm, paddingBottom: space.lg },
});
