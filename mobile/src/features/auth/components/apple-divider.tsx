import * as AppleAuthentication from "expo-apple-authentication";
import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";

import { Text } from "@/components/ui/text";
import { isGoogleSignInConfigured } from "@/features/auth/google";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

/**
 * The "or" rule above the social sign-in buttons.
 *
 * Shows when *either* provider is available, not just Apple — Android has no Apple
 * button but does have Google, and a Google button floating with no separator reads as a
 * layout bug. Equally, a divider with nothing under it reads as something that failed to
 * load, so it disappears when neither provider is offered.
 */
export function AppleDivider() {
  const t = useTranslate();
  const theme = useTheme();
  const [appleAvailable, setAppleAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void AppleAuthentication.isAvailableAsync()
      .then((value) => {
        if (!cancelled) setAppleAvailable(value);
      })
      .catch(() => {
        if (!cancelled) setAppleAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Google needs no async check: it is configured or it is not, decided at build time.
  if (!appleAvailable && !isGoogleSignInConfigured()) return null;

  return (
    <View style={styles.row} accessibilityElementsHidden importantForAccessibility="no">
      <View style={[styles.rule, { backgroundColor: theme.border }]} />
      <Text variant="caption" tone="muted">
        {t("apple.or")}
      </Text>
      <View style={[styles.rule, { backgroundColor: theme.border }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  rule: { flex: 1, height: StyleSheet.hairlineWidth },
});
