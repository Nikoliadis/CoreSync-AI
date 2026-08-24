import { Text as RNText, type TextProps } from "react-native";

import { type, useTheme } from "@/theme";

type Variant = keyof typeof import("@/theme").type;
type Tone = "default" | "secondary" | "muted" | "accent" | "critical";

type Props = TextProps & {
  variant?: Variant;
  tone?: Tone;
  /** Tabular figures, so a changing number does not shift the layout around it. */
  tabular?: boolean;
};

export function Text({ variant = "body", tone = "default", tabular, style, ...rest }: Props) {
  const theme = useTheme();

  const colors: Record<Tone, string> = {
    default: theme.text,
    secondary: theme.textSecondary,
    muted: theme.textMuted,
    // The readable accent, not the raw brand lime — see the note in tokens.ts.
    accent: theme.accentText,
    critical: theme.critical,
  };

  return (
    <RNText
      style={[
        type[variant],
        { color: colors[tone] },
        tabular && { fontVariant: ["tabular-nums"] },
        style,
      ]}
      {...rest}
    />
  );
}
