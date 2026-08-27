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
  displayName: z.string().trim().min(1, "What should we call you?").max(80),
  email: z.string().min(1, "Enter your email.").email("That doesn't look like an email."),
  // Ten characters, matching the backend. Length beats composition rules: a passphrase
  // is both stronger and easier to remember than `P@ssw0rd!`.
  password: z.string().min(10, "Use at least 10 characters — a short phrase works well."),
});

type Values = z.infer<typeof schema>;

export default function RegisterScreen() {
  const t = useTranslate();
  const router = useRouter();
  const register = useAuth((state) => state.register);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    handleSubmit,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { displayName: "", email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await register(values);
      // Straight to verification, not to the app: the account exists but the email is
      // unconfirmed, and pretending otherwise makes the first failure confusing.
      router.replace({ pathname: "/(auth)/verify", params: { email: values.email } });
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = error.fieldErrors;
        if (fields.email) setError("email", { message: fields.email });
        if (fields.password) setError("password", { message: fields.password });
        if (fields.displayName) setError("displayName", { message: fields.displayName });
        if (!fields.email && !fields.password && !fields.displayName) {
          setFormError(
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
          <Text variant="h1">{t("auth.register")}</Text>

          {formError && (
            <Text tone="critical" accessibilityRole="alert">
              {formError}
            </Text>
          )}

          <Input
            label={t("auth.name")}
            autoComplete="name"
            textContentType="name"
            error={errors.displayName?.message}
            onChangeText={(value) =>
              setValue("displayName", value, { shouldValidate: false })
            }
          />
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
            autoComplete="new-password"
            textContentType="newPassword"
            error={errors.password?.message}
            onChangeText={(value) => setValue("password", value, { shouldValidate: false })}
          />

          <Button label={t("auth.register")} loading={isSubmitting} onPress={onSubmit} />

          <AppleDivider />
          {/* Same call as on login: Apple does not distinguish signing up from
              signing in, and the server creates the account when the subject is new. */}
          <AppleSignInButton onError={setFormError} />

          <Pressable
            onPress={() => router.push("/(auth)/login")}
            accessibilityRole="link"
            style={styles.link}
          >
            <Text variant="caption" tone="secondary">
              {t("auth.haveAccount")}{" "}
              <Text variant="caption" tone="accent">
                {t("auth.login")}
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
