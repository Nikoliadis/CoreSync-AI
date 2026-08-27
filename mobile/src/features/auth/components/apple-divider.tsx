import * as AppleAuthentication from "expo-apple-authentication";
import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";

import { Text } from "@/components/ui/text";
import { space, useTheme } from "@/theme";

/**
 * The "or" rule above the Apple button.
 *
 * Its own component so it disappears together with the button. A divider left behind on
 * Android would separate the form from nothing at all, which reads as something having
 * failed to load.
 */
export function AppleDivider() {
  const theme = useTheme();
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void AppleAuthentication.isAvailableAsync()
      .then((value) => {
        if (!cancelled) setAvailable(value);
      })
      .catch(() => {
        if (!cancelled) setAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!available) return null;

  return (
    <View style={styles.row} accessibilityElementsHidden importantForAccessibility="no">
      <View style={[styles.rule, { backgroundColor: theme.border }]} />
      <Text variant="caption" tone="muted">
        or
      </Text>
      <View style={[styles.rule, { backgroundColor: theme.border }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: space.md },
  rule: { flex: 1, height: StyleSheet.hairlineWidth },
});
