import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { CloudOff, Search, Star, X } from "lucide-react-native";
import { useCallback } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { Button } from "@/components/ui/button";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  type Exercise,
  equipmentLabel,
  exerciseKeys,
  exercisesApi,
  primaryMuscle,
} from "@/features/exercises/api";
import { ExerciseThumbnailButton } from "@/features/exercises/components/exercise-media";
import { usePickedExercise } from "@/features/exercises/picked-exercise";
import { useExerciseSearch } from "@/features/exercises/use-exercise-search";
import { useTranslate } from "@/lib/i18n";
import { HIT_SIZE, radius, space, type, useTheme } from "@/theme";

const DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;

/**
 * Choose an exercise for the active workout.
 *
 * Presented as a modal over the workout rather than a push, because the workout is still
 * running underneath and losing its screen is how a session gets abandoned. The chosen
 * exercise is handed back through a small store rather than route params — an id in a URL
 * would be enough, but the name is needed too and encoding a whole object into a param is
 * how that goes wrong.
 */
export default function ExercisePickerScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const pick = usePickedExercise((state) => state.pick);
  const search = useExerciseSearch();

  // Filter metadata is reference data that almost never changes, so it is cached hard
  // rather than refetched every time the sheet opens.
  const muscleGroups = useQuery({
    queryKey: exerciseKeys.muscleGroups(),
    queryFn: exercisesApi.muscleGroups,
    staleTime: 24 * 60 * 60_000,
  });

  const onSelect = useCallback(
    (exercise: Exercise) => {
      // The real catalogue id, straight from the API. Nothing is minted here — a
      // fabricated id would be accepted locally and rejected by the server on sync,
      // taking every set logged against it with it.
      pick({ id: exercise.id, name: exercise.name });
      router.back();
    },
    [pick, router],
  );

  const showEmpty = !search.isLoading && !search.isError && search.exercises.length === 0;

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <View style={[styles.searchBox, { backgroundColor: theme.surfaceWell }]}>
          <Search size={18} color={theme.textMuted} />
          <TextInput
            autoFocus
            value={search.query}
            onChangeText={search.setQuery}
            placeholder={t("workouts.addExercise")}
            placeholderTextColor={theme.textMuted}
            accessibilityLabel={t("common.search")}
            returnKeyType="search"
            style={[styles.searchInput, { color: theme.text }]}
          />
          {search.query.length > 0 && (
            <Pressable
              onPress={() => search.setQuery("")}
              accessibilityRole="button"
              accessibilityLabel={t("common.cancel")}
              hitSlop={8}
            >
              <X size={18} color={theme.textMuted} />
            </Pressable>
          )}
        </View>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          style={styles.cancel}
        >
          <Text tone="accent">{t("common.cancel")}</Text>
        </Pressable>
      </View>

      <FlatList
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.filterRow}
        contentContainerStyle={styles.filterContent}
        keyboardShouldPersistTaps="handled"
        data={[
          { key: "favorites", label: "★", active: Boolean(search.filters.favoritesOnly) },
          ...DIFFICULTIES.map((level) => ({
            key: level,
            label: level,
            active: search.filters.difficulty === level,
          })),
          ...(muscleGroups.data ?? []).map((group) => ({
            key: group.slug,
            label: group.name,
            active: search.filters.muscleGroup === group.slug,
          })),
        ]}
        renderItem={({ item }) => (
          <Chip
            label={item.label}
            active={item.active}
            onPress={() => {
              if (item.key === "favorites") {
                search.setFilter("favoritesOnly", search.filters.favoritesOnly ? undefined : true);
              } else if ((DIFFICULTIES as readonly string[]).includes(item.key)) {
                search.setFilter("difficulty", item.key);
              } else {
                search.setFilter("muscleGroup", item.key);
              }
            }}
          />
        )}
      />

      {search.servedFromCache && (
        // Said out loud. Cached results are ordered alphabetically rather than by
        // relevance and may be incomplete, and presenting them as live results would be
        // a quiet lie.
        <View style={[styles.notice, { backgroundColor: theme.surfaceWell }]}>
          <CloudOff size={14} color={theme.textMuted} />
          <Text variant="caption" tone="muted">
            Offline — showing exercises you have loaded before.
          </Text>
        </View>
      )}

      {search.isLoading ? (
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      ) : search.isError ? (
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button label={t("common.retry")} variant="ghost" onPress={search.retry} />
        </View>
      ) : (
        <FlatList
          data={search.exercises}
          keyExtractor={(exercise) => exercise.id}
          contentContainerStyle={styles.list}
          keyboardShouldPersistTaps="handled"
          initialNumToRender={12}
          windowSize={9}
          removeClippedSubviews
          onEndReachedThreshold={0.5}
          onEndReached={search.loadMore}
          ListEmptyComponent={
            showEmpty ? (
              <View style={styles.centre}>
                <Text tone="secondary">
                  {search.servedFromCache
                    ? "Nothing cached matches that. Connect to search the full catalogue."
                    : "Nothing matched. Try a shorter word."}
                </Text>
              </View>
            ) : null
          }
          ListFooterComponent={
            search.isFetchingMore ? (
              <ActivityIndicator style={styles.footer} color={theme.textMuted} />
            ) : null
          }
          renderItem={({ item }) => (
            <ExerciseRow exercise={item} onPress={() => onSelect(item)} />
          )}
        />
      )}
    </Screen>
  );
}

function ExerciseRow({
  exercise,
  onPress,
}: {
  exercise: Exercise;
  onPress: () => void;
}) {
  const theme = useTheme();
  const router = useRouter();
  const muscle = primaryMuscle(exercise);
  const equipment = equipmentLabel(exercise);
  const detail = [muscle, equipment].filter(Boolean).join(" · ");

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={detail ? `${exercise.name}. ${detail}` : exercise.name}
      style={({ pressed }) => [
        styles.row,
        { borderBottomColor: theme.border, opacity: pressed ? 0.6 : 1 },
      ]}
    >
      <ExerciseThumbnailButton
        media={exercise.media}
        name={exercise.name}
        // Tapping the picture asks "how is this done"; tapping the row says "I am doing
        // this one". Two different intentions, so two different targets.
        onPress={() => router.push(`/exercise/${exercise.id}`)}
      />

      <View style={styles.rowText}>
        <View style={styles.rowTitle}>
          <Text numberOfLines={1} style={styles.name}>
            {exercise.name}
          </Text>
          {exercise.isFavorite && (
            <Star size={14} color={theme.accentText} fill={theme.accentText} />
          )}
        </View>
        {detail.length > 0 && (
          <Text variant="caption" tone="muted" numberOfLines={1}>
            {detail}
          </Text>
        )}
      </View>
      <Text variant="caption" tone="muted">
        {exercise.difficulty.slice(0, 3)}
      </Text>
    </Pressable>
  );
}

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      style={[
        styles.chip,
        {
          borderColor: active ? theme.accent : theme.border,
          backgroundColor: active ? `${theme.accent}1a` : "transparent",
        },
      ]}
    >
      <Text variant="caption" tone={active ? "default" : "secondary"}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  searchBox: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    height: HIT_SIZE,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
  },
  searchInput: { flex: 1, fontSize: type.body.fontSize },
  cancel: { minHeight: HIT_SIZE, justifyContent: "center", paddingHorizontal: space.xs },
  filterRow: { flexGrow: 0 },
  filterContent: { gap: space.sm, paddingHorizontal: space.lg, paddingVertical: space.sm },
  chip: {
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: space.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  notice: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md, padding: space.xl },
  list: { paddingBottom: space.xxl },
  footer: { paddingVertical: space.lg },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    minHeight: 64,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowText: { flex: 1, gap: 2 },
  rowTitle: { flexDirection: "row", alignItems: "center", gap: space.xs },
  name: { flexShrink: 1 },
});
