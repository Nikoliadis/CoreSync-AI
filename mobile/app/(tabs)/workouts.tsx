import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { CalendarDays, ChevronRight, Plus, Trophy } from "lucide-react-native";
import { ActivityIndicator, Pressable, SectionList, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { byFolder, type Routine, routineKeys, routinesApi } from "@/features/routines/api";
import {
  duration,
  relativeDay,
  type SessionSummary,
  sessionHistoryApi,
  sessionHistoryKeys,
  volume,
} from "@/features/workouts/history-list-api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * The workouts tab: plans above, history below.
 *
 * This screen used to render a hardcoded "no workouts yet" and never call the API, so it
 * said that to people who had logged fifty. Both halves are real now.
 *
 * Routines sit on top because they are what somebody opens this tab to *do*; history is
 * what they open it to *read*, and reading is the rarer trip.
 */
export default function WorkoutsScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();

  const routines = useQuery({
    queryKey: routineKeys.list(),
    queryFn: routinesApi.list,
  });

  const history = useInfiniteQuery({
    queryKey: sessionHistoryKeys.list(),
    queryFn: ({ pageParam }: { pageParam: string | null }) => sessionHistoryApi.page(pageParam),
    initialPageParam: null as string | null,
    // Keyset, not offset: new sessions land at the head of the list, and an offset would
    // show the same workout twice or skip one as it grows under the scroll.
    getNextPageParam: (page) => (page.hasMore ? page.nextCursor : null),
  });

  const sessions = history.data?.pages.flatMap((page) => page.items) ?? [];
  const grouped = byFolder(routines.data ?? []);

  return (
    <Screen edges={["top"]} padded={false}>
      <SectionList
        sections={[{ title: "history", data: sessions }]}
        keyExtractor={(session) => session.id}
        contentContainerStyle={styles.content}
        onEndReached={() => {
          if (history.hasNextPage && !history.isFetchingNextPage) void history.fetchNextPage();
        }}
        onEndReachedThreshold={0.5}
        refreshing={routines.isRefetching || history.isRefetching}
        onRefresh={() => {
          void routines.refetch();
          void history.refetch();
        }}
        ListHeaderComponent={
          <View style={styles.header}>
            <Text variant="h1">{t("tabs.workouts")}</Text>

            <Button label={t("workouts.start")} onPress={() => router.push("/workout/active")} />

            <View style={styles.sectionHead}>
              <Text variant="overline" tone="muted">
                {t("workouts.routines").toUpperCase()}
              </Text>
              <Pressable
                onPress={() => router.push("/routines/edit")}
                accessibilityRole="button"
                accessibilityLabel={t("workouts.newRoutine")}
                hitSlop={8}
                style={styles.addRoutine}
              >
                <Plus size={18} color={theme.accentText} />
              </Pressable>
            </View>

            {routines.isLoading ? (
              <ActivityIndicator color={theme.textMuted} />
            ) : grouped.length === 0 ? (
              <Card style={styles.empty}>
                <Text tone="secondary" style={styles.centred}>
                  {t("workouts.noRoutines")}
                </Text>
                <Button
                  label={t("workouts.templates")}
                  variant="secondary"
                  onPress={() => router.push("/routines/templates")}
                />
              </Card>
            ) : (
              <View style={styles.routines}>
                {grouped.map(([folder, items]) => (
                  <View key={folder ?? "__ungrouped"} style={styles.folder}>
                    {folder !== null && (
                      <Text variant="caption" tone="muted">
                        {folder}
                      </Text>
                    )}
                    {items.map((routine) => (
                      <RoutineRow key={routine.id} routine={routine} />
                    ))}
                  </View>
                ))}
                <Pressable
                  onPress={() => router.push("/routines/templates")}
                  accessibilityRole="button"
                  style={styles.templatesLink}
                >
                  <Text variant="caption" tone="accent">
                    {t("workouts.templates")}
                  </Text>
                </Pressable>
              </View>
            )}

            <View style={styles.sectionHead}>
              <Text variant="overline" tone="muted" style={styles.historyHead}>
                {t("workouts.history").toUpperCase()}
              </Text>
              <Pressable
                onPress={() => router.push("/workout/calendar")}
                accessibilityRole="button"
                accessibilityLabel={t("calendar.title")}
                hitSlop={8}
                style={styles.addRoutine}
              >
                <CalendarDays size={18} color={theme.textMuted} />
              </Pressable>
            </View>
          </View>
        }
        ListEmptyComponent={
          history.isLoading ? (
            <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
          ) : (
            <Card style={styles.empty}>
              <Text tone="secondary" style={styles.centred}>
                {t("workouts.noHistory")}
              </Text>
            </Card>
          )
        }
        renderItem={({ item }) => <HistoryRow session={item} />}
        ListFooterComponent={
          history.isFetchingNextPage ? (
            <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
          ) : null
        }
      />
    </Screen>
  );
}

function RoutineRow({ routine }: { routine: Routine }) {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();

  return (
    <Pressable
      onPress={() => router.push(`/routines/${routine.id}`)}
      accessibilityRole="button"
      accessibilityLabel={`${routine.name}, ${routine.exercises.length} exercises`}
      style={({ pressed }) => [
        styles.routineRow,
        { borderColor: theme.border, opacity: pressed ? 0.6 : 1 },
      ]}
    >
      <View style={styles.grow}>
        <Text numberOfLines={1}>{routine.name}</Text>
        <Text variant="caption" tone="muted">
          {t("workouts.exerciseCount", { count: routine.exercises.length })} ·{" "}
          {t("workouts.setCount", { count: routine.totalSets })}
        </Text>
      </View>
      <ChevronRight size={18} color={theme.textMuted} />
    </Pressable>
  );
}

function HistoryRow({ session }: { session: SessionSummary }) {
  const theme = useTheme();
  const router = useRouter();

  return (
    <Pressable
      onPress={() => router.push(`/workout/${session.id}`)}
      accessibilityRole="button"
      accessibilityLabel={`${session.name}, ${relativeDay(session.localDate)}, ${session.totalSets} sets`}
      style={({ pressed }) => [
        styles.historyRow,
        { borderBottomColor: theme.border, opacity: pressed ? 0.6 : 1 },
      ]}
    >
      <View style={styles.grow}>
        <View style={styles.historyTitle}>
          <Text numberOfLines={1} style={styles.grow}>
            {session.name}
          </Text>
          {session.prCount > 0 && <Trophy size={13} color={theme.accentText} />}
        </View>
        <Text variant="caption" tone="muted" tabular>
          {relativeDay(session.localDate)} · {duration(session.durationSeconds)} ·{" "}
          {session.totalSets} sets · {volume(session.totalVolumeKg)}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, paddingBottom: space.xxl },
  header: { gap: space.md, marginBottom: space.sm },
  sectionHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: space.sm,
  },
  addRoutine: { padding: space.xs },
  routines: { gap: space.md },
  folder: { gap: space.xs },
  routineRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    minHeight: 56,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  templatesLink: { paddingVertical: space.xs },
  historyHead: { marginTop: space.md },
  historyRow: {
    minHeight: 56,
    justifyContent: "center",
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  historyTitle: { flexDirection: "row", alignItems: "center", gap: space.xs },
  grow: { flex: 1 },
  empty: { alignItems: "center", gap: space.md, paddingVertical: space.xl },
  centred: { textAlign: "center" },
  spinner: { marginVertical: space.lg },
});
