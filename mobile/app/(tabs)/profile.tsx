import { ScrollView, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { SUPPORTED_LOCALES, useI18n, useTranslate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { HIT_SIZE, radius, space, useTheme, useThemePreference, type ThemePreference } from "@/theme";

const THEME_OPTIONS: readonly ThemePreference[] = ["system", "dark", "light"];

export default function ProfileScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const user = useAuth((state) => state.user);
  const logout = useAuth((state) => state.logout);
  const { preference, setPreference } = useThemePreference();
  const { locale, setLocale } = useI18n();

  const themeLabels: Record<ThemePreference, string> = {
    system: t("profile.themeSystem"),
    dark: t("profile.themeDark"),
    light: t("profile.themeLight"),
  };

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text variant="h1">{t("tabs.profile")}</Text>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("profile.personal").toUpperCase()}
          </Text>
          <Text variant="h3">{user?.displayName ?? "—"}</Text>
          <Text variant="caption" tone="muted">
            {user?.email ?? ""}
          </Text>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("profile.theme").toUpperCase()}
          </Text>
          <View style={styles.chips}>
            {THEME_OPTIONS.map((option) => (
              <Chip
                key={option}
                label={themeLabels[option]}
                active={preference === option}
                onPress={() => setPreference(option)}
              />
            ))}
          </View>
        </Card>

        <Card style={styles.card}>
          <Text variant="overline" tone="muted">
            {t("profile.language").toUpperCase()}
          </Text>
          <View style={styles.chips}>
            {SUPPORTED_LOCALES.map((option) => (
              <Chip
                key={option}
                label={option.toUpperCase()}
                active={locale === option}
                onPress={() => setLocale(option)}
              />
            ))}
          </View>
          {locale === "el" && (
            /* Honest about the state of it: the catalogue is not populated yet, and
               falling back to English silently would look like a bug. */
            <Text variant="caption" tone="muted">
              Greek is being translated. Untranslated text stays in English.
            </Text>
          )}
        </Card>

        <Button
          label={t("auth.logout")}
          variant="ghost"
          style={{ borderColor: theme.border }}
          onPress={() => void logout()}
        />
      </ScrollView>
    </Screen>
  );
}

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <Text
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      variant="caption"
      style={[
        styles.chip,
        {
          borderColor: active ? theme.accent : theme.border,
          backgroundColor: active ? `${theme.accent}1a` : "transparent",
          color: theme.text,
        },
      ]}
    >
      {label}
    </Text>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  card: { gap: space.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    minHeight: HIT_SIZE,
    lineHeight: HIT_SIZE,
    paddingHorizontal: space.lg,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
  },
});
