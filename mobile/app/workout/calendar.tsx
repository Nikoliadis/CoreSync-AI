import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ChevronLeft, ChevronRight } from "lucide-react-native";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from "react-native";

import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  busiestVolume,
  type CalendarDay,
  calendarApi,
  calendarKeys,
  intensity,
  monthBounds,
  monthGrid,
  monthTotals,
  shiftMonth,
  toLocalISO,
} from "@/features/workouts/calendar-api";
import { useI18n, useTranslate } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * Which days you trained, as a month at a glance.
 *
 * The value is the pattern rather than any single day — three weeks of Tuesdays and
 * Thursdays with nothing at the weekend is a fact about somebody's life that no list of
 * sessions makes visible.
 */
export default function CalendarScreen() {
  const t = useTranslate();
  const { locale } = useI18n();
  const theme = useTheme();
  const router = useRouter();

  const [month, setMonth] = useState(() => new Date());
  const { from, to } = monthBounds(month);

  const days = useQuery({
    queryKey: calendarKeys.range(from, to),
    queryFn: () => calendarApi.range(from, to),
  });

  const byDate = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    for (const day of days.data ?? []) map.set(day.localDate, day);
    return map;
  }, [days.data]);

  const cells = useMemo(() => monthGrid(month), [month]);
  const busiest = busiestVolume(days.data ?? []);
  const totals = monthTotals(days.data ?? []);
  const today = toLocalISO(new Date());

  // Weekday initials from the active locale, Monday first. Deriving them rather than
  // listing them means the Greek build reads Δ Τ Τ Π Π Σ Κ without a second catalogue.
  const weekdays = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(locale === "el" ? "el-GR" : "en-GB", {
      weekday: "short",
    });
    // 2026-01-05 was a Monday.
    return Array.from({ length: 7 }, (_, index) =>
      formatter.format(new Date(2026, 0, 5 + index)).slice(0, 2),
    );
  }, [locale]);

  const monthLabel = new Intl.DateTimeFormat(locale === "el" ? "el-GR" : "en-GB", {
    month: "long",
    year: "numeric",
  }).format(month);

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <Text variant="h3" style={styles.grow}>
          {t("calendar.title")}
        </Text>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.close}>
          <Text tone="accent">{t("common.done")}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.monthRow}>
          <Pressable
            onPress={() => setMonth((current) => shiftMonth(current, -1))}
            accessibilityRole="button"
            accessibilityLabel={t("calendar.previousMonth")}
            hitSlop={8}
            style={styles.arrow}
          >
            <ChevronLeft size={20} color={theme.textMuted} />
          </Pressable>

          <Text variant="body" style={styles.monthLabel}>
            {monthLabel}
          </Text>

          <Pressable
            onPress={() => setMonth((current) => shiftMonth(current, 1))}
            accessibilityRole="button"
            accessibilityLabel={t("calendar.nextMonth")}
            hitSlop={8}
            style={styles.arrow}
          >
            <ChevronRight size={20} color={theme.textMuted} />
          </Pressable>
        </View>

        <View style={styles.weekdays}>
          {weekdays.map((label, index) => (
            <Text
              key={index}
              variant="caption"
              tone="muted"
              style={styles.weekday}
              accessibilityElementsHidden
              importantForAccessibility="no"
            >
              {label}
            </Text>
          ))}
        </View>

        {days.isLoading ? (
          <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
        ) : (
          <View style={styles.grid}>
            {cells.map((cell) => {
              const day = byDate.get(cell.date);
              const level = intensity(day, busiest);
              const isToday = cell.date === today;

              return (
                // Not tappable. The calendar answers "when did I train", and the
                // aggregate it is built from carries no session ids — so a tap could
                // only guess at which workout to open, and guessing wrong is worse
                // than not offering the tap.
                <View
                  key={cell.date}
                  accessible
                  accessibilityLabel={
                    day?.workoutCount
                      ? t("calendar.dayTrained", {
                          date: cell.date,
                          count: day.workoutCount,
                        })
                      : t("calendar.dayRest", { date: cell.date })
                  }
                  style={[
                    styles.cell,
                    {
                      backgroundColor:
                        level === 0
                          ? theme.surfaceWell
                          : // Opacity carries the intensity, so the scale stays one hue
                            // and reads as "more" rather than as different categories.
                            `${theme.accent}${["", "40", "80", "ff"][level] ?? "ff"}`,
                      borderColor: isToday ? theme.accentText : "transparent",
                      opacity: cell.inMonth ? 1 : 0.25,
                    },
                  ]}
                >
                  <Text
                    variant="caption"
                    tone={level >= 2 ? "default" : "muted"}
                    style={level >= 2 ? { color: theme.accentInk } : undefined}
                    tabular
                  >
                    {cell.day}
                  </Text>
                </View>
              );
            })}
          </View>
        )}

        <Card style={styles.totals}>
          <Total value={String(totals.daysTrained)} label={t("calendar.daysTrained")} />
          <Total
            value={Math.round(totals.volumeKg).toLocaleString()}
            label={t("history.volume")}
          />
          <Total value={totals.hours.toFixed(1)} label={t("calendar.hours")} />
        </Card>
      </ScrollView>
    </Screen>
  );
}

function Total({ value, label }: { value: string; label: string }) {
  return (
    <View style={styles.total}>
      <Text variant="h3" tabular>
        {value}
      </Text>
      <Text variant="caption" tone="muted">
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  grow: { flex: 1 },
  close: { paddingVertical: space.sm },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  monthRow: { flexDirection: "row", alignItems: "center", gap: space.md },
  arrow: { padding: space.xs },
  monthLabel: { flex: 1, textAlign: "center", textTransform: "capitalize" },
  weekdays: { flexDirection: "row" },
  weekday: { flex: 1, textAlign: "center" },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  cell: {
    width: `${100 / 7}%`,
    aspectRatio: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.sm,
    borderWidth: 1,
  },
  spinner: { marginVertical: space.xl },
  totals: { flexDirection: "row", justifyContent: "space-around" },
  total: { alignItems: "center", gap: 2 },
});
