import { useState } from "react";
import { StyleSheet, TextInput, View, type TextInputProps } from "react-native";

import { Text } from "./text";
import { HIT_SIZE, radius, space, type, useTheme } from "@/theme";

type Props = TextInputProps & {
  label?: string;
  hint?: string;
  error?: string;
};

/**
 * A labelled field.
 *
 * The label is a real label, always visible — placeholder-as-label disappears the moment
 * someone starts typing, which is exactly when they most need to know what the field is.
 */
export function Input({ label, hint, error, style, ...rest }: Props) {
  const theme = useTheme();
  const [focused, setFocused] = useState(false);

  return (
    <View style={styles.wrapper}>
      {label && (
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
      )}
      <TextInput
        // React Native has no `aria-invalid`, so the error is folded into the label —
        // otherwise a screen reader user gets a red border they cannot see and no words.
        // Colour never carries the state alone for sighted users either; the message
        // below does the work and the border only reinforces it.
        accessibilityLabel={error && label ? `${label}. ${error}` : (error ?? label)}
        placeholderTextColor={theme.textMuted}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={[
          styles.input,
          {
            color: theme.text,
            backgroundColor: theme.surfaceWell,
            borderColor: error
              ? theme.critical
              : focused
                ? theme.borderStrong
                : theme.border,
          },
          style,
        ]}
        {...rest}
      />
      {error ? (
        <Text variant="caption" tone="critical" accessibilityRole="alert">
          {error}
        </Text>
      ) : hint ? (
        <Text variant="caption" tone="muted">
          {hint}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: space.xs },
  input: {
    minHeight: HIT_SIZE + 8,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.lg,
    fontSize: type.body.fontSize,
  },
});
