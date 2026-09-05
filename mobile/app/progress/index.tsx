import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Camera, ChevronRight, Plus } from "lucide-react-native";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  useWindowDimensions,
} from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  changeDirection,
  progressApi,
  progressKeys,
  signedKg,
  SITE_LABELS,
  weeklyRate,
} from "@/features/progress/api";
import { WeightChart } from "@/features/progress/components/weight-chart";
import { useTranslate } from "@/lib/i18n";
import { radius, space, type, useTheme } from "@/theme";

const RANGES = [
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
  { days: 365, label: "1y" },
] as const;

/**
 * Weight, measurements and training volume.
 *
 * Ordered by how often somebody looks: weight daily, measurements monthly, volume when
 * they are wondering whether a programme is doing anything.
 */
export default function ProgressScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const { width } = useWindowDimensions();

  const [days, setDays] = useState<number>(90);

  const weight = useQuery({
    queryKey: progressKeys.weight(days),
    queryFn: () => progressApi.weight(days),
  });

  const measurements = useQuery({
    queryKey: progressKeys.measurementSeries(),
    queryFn: progressApi.measurementSeries,
  });

  const volume = useQuery({
    queryKey: progressKeys.volume(12),
    queryFn: () => progressApi.volume(12),
  });

  const series = weight.data;
  const rate = weeklyRate(series?.weeklyRateKg ?? null);
  const direction = changeDirection(series?.changeKg ?? null);
  const chartWidth = width - space.lg * 2 - space.lg * 2;

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={weight.isRefetching}
            onRefresh={() => {
              void weight.refetch();
              void measurements.refetch();
              void volume.refetch();
            }}
            tintColor={theme.textMuted}
          />
        }
      >
        <Text variant="h1">{t("progress.title")}</Text>

        <Card style={styles.section}>
          <View style={styles.sectionHead}>
            <Text variant="overline" tone="muted">
              WEIGHT
            </Text>
            <View style={styles.ranges}>
              {RANGES.map((range) => (
                <Pressable
                  key={range.days}
                  onPress={() => setDays(range.days)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: days === range.days }}
                  style={[
                    styles.range,
                    {
                      borderColor: days === range.days ? theme.accent : theme.border,
                      backgroundColor:
                        days === range.days ? `${theme.accent}1a` : "transparent",
                    },
                  ]}
                >
                  <Text variant="caption" tone={days === range.days ? "default" : "muted"}>
                    {range.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>

          {weight.isLoading ? (
            <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
          ) : (
            <>
              <View style={styles.headline}>
                <Text variant="display" tabular>
                  {series?.latestTrendKg
                    ? Number(series.latestTrendKg).toFixed(1)
                    : series?.latestWeightKg
                      ? Number(series.latestWeightKg).toFixed(1)
                      : "—"}
                </Text>
                <Text variant="caption" tone="muted">
                  {t("progress.kgTrend")}
                </Text>
                <Text
                  variant="caption"
                  // Direction is stated, not judged. Someone gaining muscle wants this
                  // going up, and painting their success red teaches them to distrust it.
                  tone={direction === "flat" ? "muted" : "secondary"}
                  style={styles.change}
                  tabular
                >
                  {signedKg(series?.changeKg ?? null)}
                  {rate ? ` · ${rate}` : ""}
                </Text>
              </View>

              <WeightChart points={series?.points ?? []} width={chartWidth} />

              {series?.projection && !series.projection.isMovingAway
                ? series.projection.projectedDate && (
                    <Text variant="caption" tone="muted">
                      On track for {Number(series.projection.targetWeightKg).toFixed(1)} kg
                      around {series.projection.projectedDate}
                    </Text>
                  )
                : series?.projection?.isMovingAway && (
                    // No date, because projecting one from a trend heading the wrong way
                    // would be arithmetic dressed up as encouragement.
                    <Text variant="caption" tone="muted">
                      {t("progress.movingAway")}
                    </Text>
                  )}

              <LogWeightRow />
            </>
          )}
        </Card>

        <Card style={styles.section}>
          <View style={styles.sectionHead}>
            <Text variant="overline" tone="muted">
              MEASUREMENTS
            </Text>
            <Pressable
              onPress={() => router.push("/progress/measurements")}
              accessibilityRole="button"
              accessibilityLabel={t("progress.recordMeasurements")}
              hitSlop={8}
            >
              <Plus size={18} color={theme.accentText} />
            </Pressable>
          </View>

          {measurements.isLoading ? (
            <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
          ) : (measurements.data?.trends ?? []).length === 0 ? (
            <Text variant="caption" tone="secondary">
              {t("progress.nothingRecorded")}
            </Text>
          ) : (
            (measurements.data?.trends ?? []).map((trend) => (
              <View key={trend.site} style={styles.measureRow}>
                <Text variant="caption" style={styles.grow}>
                  {SITE_LABELS[trend.site as keyof typeof SITE_LABELS] ?? trend.site}
                </Text>
                <Text variant="caption" tone="muted" tabular>
                  {Number(trend.latestValueCm).toFixed(1)} cm
                </Text>
                <Text variant="caption" tone="secondary" style={styles.delta} tabular>
                  {Number(trend.changeCm) > 0 ? "+" : Number(trend.changeCm) < 0 ? "−" : ""}
                  {Math.abs(Number(trend.changeCm)).toFixed(1)}
                </Text>
              </View>
            ))
          )}
        </Card>

        <Pressable
          onPress={() => router.push("/progress/photos")}
          accessibilityRole="button"
          accessibilityLabel={t("photos.title")}
        >
          <Card style={styles.linkRow}>
            <Camera size={18} color={theme.accentText} />
            <Text variant="body" style={styles.grow}>
              {t("photos.title")}
            </Text>
            <ChevronRight size={18} color={theme.textMuted} />
          </Card>
        </Pressable>

        <Card style={styles.section}>
          <Text variant="overline" tone="muted">
            {t("progress.volumeByMuscle")}
          </Text>
          {volume.isLoading ? (
            <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
          ) : (
            <VolumeBreakdown buckets={volume.data ?? []} />
          )}
        </Card>
      </ScrollView>
    </Screen>
  );
}

/** Inline, because a weigh-in is two taps and does not deserve its own screen. */
function LogWeightRow() {
  const t = useTranslate();
  const theme = useTheme();
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const weight = Number(value.replace(",", "."));
    if (!Number.isFinite(weight) || weight <= 0 || saving) return;

    setSaving(true);
    try {
      await progressApi.logWeight({ weightKg: weight });
      setValue("");
      await queryClient.invalidateQueries({ queryKey: progressKeys.all });
    } catch (error) {
      console.warn("could not log weight", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.logRow}>
      <TextInput
        value={value}
        onChangeText={setValue}
        keyboardType="decimal-pad"
        placeholder={t("progress.todaysWeight")}
        placeholderTextColor={theme.textMuted}
        accessibilityLabel={t("progress.todaysWeightLabel")}
        style={[styles.weightField, { color: theme.text, backgroundColor: theme.surfaceWell }]}
      />
      <Button
        label={t("common.save")}
        size="sm"
        disabled={value.trim() === "" || saving}
        onPress={() => void submit()}
      />
    </View>
  );
}

/**
 * Relative bars, no axis.
 *
 * The useful question is "am I neglecting a muscle group", which is a comparison between
 * bars. An absolute kilogram axis would answer a question nobody asks and take the width
 * the labels need.
 */
function VolumeBreakdown({ buckets }: { buckets: readonly { volumeByMuscleGroup: Record<string, string> }[] }) {
  const t = useTranslate();
  const theme = useTheme();

  const totals = new Map<string, number>();
  for (const bucket of buckets) {
    for (const [group, value] of Object.entries(bucket.volumeByMuscleGroup)) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) totals.set(group, (totals.get(group) ?? 0) + parsed);
    }
  }

  const ranked = [...totals.entries()].sort(([, a], [, b]) => b - a);
  if (ranked.length === 0) {
    return (
      <Text variant="caption" tone="secondary">
        {t("progress.noCompletedWorkouts")}
      </Text>
    );
  }

  const highest = ranked[0]?.[1] ?? 1;

  return (
    <View style={styles.bars}>
      {ranked.map(([group, value]) => (
        <View key={group} style={styles.barRow}>
          <Text variant="caption" tone="secondary" style={styles.barLabel} numberOfLines={1}>
            {group.replace(/_/g, " ")}
          </Text>
          <View style={[styles.barTrack, { backgroundColor: theme.surfaceWell }]}>
            <View
              style={[
                styles.barFill,
                {
                  backgroundColor: theme.accent,
                  // Floored so a group with a little volume is still visibly present
                  // rather than an empty track that reads as "none".
                  width: `${Math.max(2, (value / highest) * 100)}%`,
                },
              ]}
            />
          </View>
          <Text variant="caption" tone="muted" style={styles.barValue} tabular>
            {Math.round(value).toLocaleString()}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  section: { gap: space.sm },
  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  ranges: { flexDirection: "row", gap: space.xs },
  range: {
    minHeight: 28,
    justifyContent: "center",
    paddingHorizontal: space.sm,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  headline: { flexDirection: "row", alignItems: "baseline", gap: space.xs },
  change: { marginLeft: "auto" },
  linkRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  spinner: { marginVertical: space.lg },
  logRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  weightField: {
    flex: 1,
    height: 44,
    paddingHorizontal: space.md,
    borderRadius: radius.sm,
    fontSize: type.body.fontSize,
    fontVariant: ["tabular-nums"],
  },
  measureRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  grow: { flex: 1 },
  delta: { minWidth: 48, textAlign: "right" },
  bars: { gap: space.xs },
  barRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  barLabel: { width: 84 },
  barTrack: { flex: 1, height: 8, borderRadius: 4, overflow: "hidden" },
  barFill: { height: 8, borderRadius: 4 },
  barValue: { width: 56, textAlign: "right" },
});
