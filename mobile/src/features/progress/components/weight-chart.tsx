import { StyleSheet, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import { Text } from "@/components/ui/text";
import { space, useTheme } from "@/theme";

import { type WeightPoint, weightBounds } from "../api";

/**
 * Weigh-ins and the trend line, on one scale.
 *
 * The dots are what the scale said; the line is what it means. Bodyweight swings two
 * kilos on water, salt and time of day, so a chart of raw weigh-ins alone shows progress
 * appearing to reverse every other day — which is how people talk themselves out of a
 * plan that is working. Drawing both, sharing one axis, is the whole point: you can see
 * the noise *and* see through it.
 *
 * Hand-drawn with `react-native-svg` rather than a charting library. This is two paths
 * and some circles; a chart package would be a megabyte of bundle and a styling API to
 * fight for a picture with no axes, no legend and no interaction.
 */
export function WeightChart({
  points,
  height = 160,
  width,
}: {
  points: readonly WeightPoint[];
  height?: number;
  width: number;
}) {
  const theme = useTheme();

  if (points.length === 0) {
    return (
      <View style={[styles.empty, { height }]}>
        <Text variant="caption" tone="muted">
          No weigh-ins yet
        </Text>
      </View>
    );
  }

  const { min, max } = weightBounds(points);
  const span = max - min;
  const inset = 6;
  const usableHeight = height - inset * 2;

  // A single point has no horizontal span to divide by; place it in the middle rather
  // than dividing by zero and painting NaN into the path.
  const x = (index: number) =>
    points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
  const y = (value: number) => inset + (1 - (value - min) / span) * usableHeight;

  const line = (pick: (point: WeightPoint) => number) =>
    points
      .map((point, index) => {
        const value = pick(point);
        if (!Number.isFinite(value)) return null;
        return `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(value).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  const trendPath = line((point) => Number(point.trendKg));

  return (
    <Svg width={width} height={height}>
      {/* The trend first, so the dots sit on top of it rather than under. */}
      {trendPath.length > 0 && (
        <Path d={trendPath} stroke={theme.accent} strokeWidth={2.5} fill="none" />
      )}
      {points.map((point, index) => {
        const value = Number(point.weightKg);
        if (!Number.isFinite(value)) return null;
        return (
          <Circle
            key={`${point.localDate}-${String(index)}`}
            cx={x(index)}
            cy={y(value)}
            r={2.5}
            fill={theme.textMuted}
          />
        );
      })}
    </Svg>
  );
}

const styles = StyleSheet.create({
  empty: { alignItems: "center", justifyContent: "center", paddingVertical: space.lg },
});
