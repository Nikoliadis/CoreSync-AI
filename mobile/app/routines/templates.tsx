import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, FlatList, Pressable, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { prescription, type Routine, routineKeys, routinesApi } from "@/features/routines/api";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

/**
 * Curated starter routines.
 *
 * The answer to an empty Routines list, which is otherwise a blank page asking somebody
 * who has never lifted to design a training programme. Adopting copies the template into
 * their own routines, so editing it afterwards changes their copy and never the original.
 */
export default function TemplatesScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [adopting, setAdopting] = useState<string | null>(null);

  const templates = useQuery({
    queryKey: routineKeys.templates(),
    queryFn: routinesApi.templates,
  });

  const adopt = async (template: Routine) => {
    if (adopting) return;
    setAdopting(template.id);
    try {
      const mine = await routinesApi.adopt(template.id);
      await queryClient.invalidateQueries({ queryKey: routineKeys.all });
      // Straight into the copy, not back to the list: the next thing anybody wants is to
      // look at what they just took, or start it.
      router.replace(`/routines/${mine.id}`);
    } catch (error) {
      console.warn("could not adopt template", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setAdopting(null);
    }
  };

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <Text variant="h2" style={styles.grow}>
          {t("workouts.templates")}
        </Text>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.cancel}>
          <Text tone="accent">{t("common.cancel")}</Text>
        </Pressable>
      </View>

      {templates.isLoading ? (
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      ) : templates.isError ? (
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button
            label={t("common.retry")}
            variant="ghost"
            onPress={() => void templates.refetch()}
          />
        </View>
      ) : (
        <FlatList
          data={templates.data ?? []}
          keyExtractor={(template) => template.id}
          contentContainerStyle={styles.list}
          ListEmptyComponent={
            <View style={styles.centre}>
              <Text tone="secondary">No templates available.</Text>
            </View>
          }
          renderItem={({ item }) => (
            <Card style={styles.template}>
              <Text variant="h3">{item.name}</Text>
              <Text variant="caption" tone="muted">
                {t("workouts.exerciseCount", { count: item.exercises.length })} ·{" "}
                {t("workouts.setCount", { count: item.totalSets })}
                {item.estimatedMinutes ? ` · ~${item.estimatedMinutes} min` : ""}
              </Text>

              {item.notes ? (
                <Text variant="caption" tone="secondary">
                  {item.notes}
                </Text>
              ) : null}

              <View style={styles.exercises}>
                {item.exercises.slice(0, 5).map((exercise) => (
                  <Text key={exercise.id} variant="caption" tone="secondary" numberOfLines={1}>
                    {exercise.exerciseName ?? "Exercise"} · {prescription(exercise.sets)}
                  </Text>
                ))}
                {item.exercises.length > 5 && (
                  <Text variant="caption" tone="muted">
                    +{item.exercises.length - 5} more
                  </Text>
                )}
              </View>

              <Button
                label={adopting === item.id ? t("common.loading") : t("workouts.useTemplate")}
                variant="secondary"
                disabled={adopting !== null}
                onPress={() => void adopt(item)}
              />
            </Card>
          )}
        />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  cancel: { paddingHorizontal: space.xs, paddingVertical: space.sm },
  grow: { flex: 1 },
  centre: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: space.md,
    padding: space.xl,
  },
  list: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  template: { gap: space.sm },
  exercises: { gap: 2 },
});
