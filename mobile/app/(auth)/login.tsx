import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "expo-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, View } from "react-native";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { AppleDivider } from "@/features/auth/components/apple-divider";
import { AppleSignInButton } from "@/features/auth/components/apple-sign-in-button";
import { ApiError } from "@/lib/api/client";
import { useTranslate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { space } from "@/theme";

/**
 * Mirrors the backend's constraints so a typo is caught before a round trip. The server
 * remains the authority — this is a courtesy, never the enforcement.
 */
const schema = z.object({
  email: z.string().min(1, "Enter your email.").email("That doesn't look like an email."),
  password: z.string().min(1, "Enter your password."),
});

type Values = z.infer<typeof schema>;

export default function LoginScreen() {
  const t = useTranslate();
  const router = useRouter();
  const login = useAuth((state) => state.login);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    handleSubmit,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values.email, values.password);
      router.replace("/(tabs)");
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = error.fieldErrors;
        if (fields.email) setError("email", { message: fields.email });
        if (fields.password) setError("password", { message: fields.password });
        if (!fields.email && !fields.password) {
          setFormError(
            // Deliberately does not say which half was wrong: that turns the form into
            // an oracle for which email addresses have accounts.
            error.isOffline ? t("common.offline") : error.message,
          );
        }
      } else {
        setFormError(t("common.errorBody"));
      }
    }
  });

  return (
    <Screen edges={["top", "bottom"]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.fill}
      >
        <View style={styles.form}>
          <Text variant="h1">{t("auth.login")}</Text>

          {formError && (
            <Text tone="critical" accessibilityRole="alert">
              {formError}
            </Text>
          )}

          <Input
            label={t("auth.email")}
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            textContentType="emailAddress"
            error={errors.email?.message}
            onChangeText={(value) => setValue("email", value, { shouldValidate: false })}
          />
          <Input
            label={t("auth.password")}
            secureTextEntry
            autoComplete="current-password"
            textContentType="password"
            error={errors.password?.message}
            onChangeText={(value) => setValue("password", value, { shouldValidate: false })}
          />

          <Button label={t("auth.login")} loading={isSubmitting} onPress={onSubmit} />

          <AppleDivider />
          <AppleSignInButton onError={setFormError} />

          <Pressable
            onPress={() => router.push("/(auth)/register")}
            accessibilityRole="link"
            style={styles.link}
          >
            <Text variant="caption" tone="secondary">
              {t("auth.noAccount")}{" "}
              <Text variant="caption" tone="accent">
                {t("auth.register")}
              </Text>
            </Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  form: { flex: 1, justifyContent: "center", gap: space.lg },
  link: { alignSelf: "center", paddingVertical: space.md },
});
