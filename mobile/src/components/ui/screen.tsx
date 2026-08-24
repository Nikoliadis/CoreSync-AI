import { StyleSheet, View, type ViewProps } from "react-native";
import { SafeAreaView, type Edge } from "react-native-safe-area-context";

import { space, useTheme } from "@/theme";

type Props = ViewProps & {
  /** Which insets to respect. Tab screens skip the bottom — the bar already owns it. */
  edges?: readonly Edge[];
  padded?: boolean;
};

export function Screen({
  edges = ["top"],
  padded = true,
  style,
  ...rest
}: Props) {
  const theme = useTheme();
  return (
    <SafeAreaView edges={edges} style={[styles.fill, { backgroundColor: theme.bg }]}>
      <View style={[styles.fill, padded && styles.padded, style]} {...rest} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  padded: { paddingHorizontal: space.lg },
});
