import { useLocalSearchParams, useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { useTranslate } from "@/lib/i18n";
import { space } from "@/theme";

export default function VerifyScreen() {
  const t = useTranslate();
  const router = useRouter();
  const { email } = useLocalSearchParams<{ email?: string }>();

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={styles.body}>
        <Text variant="h1">{t("auth.verifyTitle")}</Text>
        <Text variant="body" tone="secondary">
          {t("auth.verifyBody", { email: email ?? "" })}
        </Text>
      </View>
      <Button
        label={t("auth.login")}
        variant="ghost"
        onPress={() => router.replace("/(auth)/login")}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  body: { flex: 1, justifyContent: "center", gap: space.md },
});
