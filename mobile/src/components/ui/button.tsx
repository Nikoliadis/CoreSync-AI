import * as Haptics from "expo-haptics";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  type PressableProps,
  type ViewStyle,
} from "react-native";

import { HIT_SIZE, radius, space, type, useTheme } from "@/theme";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

type Props = Omit<PressableProps, "style" | "children"> & {
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  /** Fires a light impact on press. On by default for anything that changes state. */
  haptic?: boolean;
  /**
   * Rendered before the label.
   *
   * For provider marks, which brand guidelines require beside the wording rather than
   * instead of it. Hidden from screen readers — the button's own label already says what
   * it does, and announcing "image, Google" before it would read twice.
   */
  icon?: React.ReactNode;
  style?: ViewStyle;
};

const HEIGHTS: Record<ButtonSize, number> = {
  // Never below HIT_SIZE, even at "small". A gym app's smallest button is still pressed
  // with a chalked thumb.
  sm: HIT_SIZE,
  md: 52,
  lg: 60,
};

export function Button({
  label,
  variant = "primary",
  size = "md",
  loading = false,
  haptic = true,
  icon,
  disabled,
  onPress,
  style,
  ...rest
}: Props) {
  const theme = useTheme();
  const isDisabled = disabled || loading;

  const background: Record<ButtonVariant, string> = {
    primary: theme.accent,
    secondary: theme.surfaceWell,
    ghost: "transparent",
    danger: theme.critical,
  };
  const foreground: Record<ButtonVariant, string> = {
    // Ink on lime, never white — the accent is bright enough that white on it is
    // unreadable in daylight.
    primary: theme.accentInk,
    secondary: theme.text,
    ghost: theme.text,
    danger: "#ffffff",
  };

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      onPress={(event) => {
        if (haptic) void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress?.(event);
      }}
      style={({ pressed }) => [
        styles.base,
        {
          height: HEIGHTS[size],
          backgroundColor: background[variant],
          borderColor: variant === "ghost" ? theme.border : "transparent",
          borderWidth: variant === "ghost" ? StyleSheet.hairlineWidth : 0,
          // Opacity rather than a colour shift, so every variant reads the same when
          // pressed without four more tokens.
          opacity: isDisabled ? 0.45 : pressed ? 0.85 : 1,
        },
        style,
      ]}
      {...rest}
    >
      {loading ? (
        <ActivityIndicator color={foreground[variant]} />
      ) : (
        <>
          {icon ? (
            <View style={styles.icon} accessibilityElementsHidden importantForAccessibility="no">
              {icon}
            </View>
          ) : null}
          <Text style={[styles.label, { color: foreground[variant] }]} numberOfLines={1}>
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.md,
    paddingHorizontal: space.xl,
  },
  icon: { marginRight: space.sm },
  label: {
    fontSize: type.body.fontSize,
    fontWeight: "600",
  },
});
