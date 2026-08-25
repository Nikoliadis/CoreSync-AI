import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { BadgeCheck } from "lucide-react-native";
import { ActivityIndicator, ScrollView, StyleSheet, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { exerciseKeys, exercisesApi } from "@/features/exercises/api";
import { ExerciseMediaViewer } from "@/features/exercises/components/exercise-media";
import { useTranslate } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * How to do it: the demonstration, the muscles, the cues.
 *
 * Reachable from the picker and from the active workout, because the moment somebody
 * needs this is mid-set, when they are not sure they are doing it right — not while
 * browsing a catalogue at a desk.
 */
export default function ExerciseDetailScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();

  const exercise = useQuery({
    queryKey: exerciseKeys.detail(id),
    queryFn: () => exercisesApi.get(id),
    enabled: Boolean(id),
    // The catalogue is effectively static; the server sends a long Cache-Control for the
    // same reason. Refetching a movement's description between sets earns nothing.
    staleTime: 24 * 60 * 60 * 1000,
  });

  if (exercise.isLoading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  if (exercise.isError || !exercise.data) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button
            label={t("common.retry")}
            variant="ghost"
            onPress={() => void exercise.refetch()}
          />
          <Button label={t("common.cancel")} variant="ghost" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const movement = exercise.data;
  const primary = movement.muscles.filter((muscle) => muscle.role === "primary");
  const secondary = movement.muscles.filter((muscle) => muscle.role !== "primary");

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView contentContainerStyle={styles.content}>
        <ExerciseMediaViewer media={movement.media} name={movement.name} />

        <View style={styles.body}>
          <View style={styles.titleRow}>
            <Text variant="h1" style={styles.grow}>
              {movement.name}
            </Text>
            {movement.isVerified && <BadgeCheck size={20} color={theme.accentText} />}
          </View>

          <View style={styles.chips}>
            {movement.equipment.map((item) => (
              <Chip key={item}>{item.replace(/_/g, " ")}</Chip>
            ))}
            <Chip>{movement.difficulty}</Chip>
          </View>

          {movement.description ? (
            <Text variant="body" tone="secondary">
              {movement.description}
            </Text>
          ) : null}

          {movement.instructions && movement.instructions.length > 0 ? (
            <Card style={styles.section}>
              <Text variant="overline" tone="muted">
                HOW TO
              </Text>
              {movement.instructions.map((step, position) => (
                <View key={step} style={styles.step}>
                  <Text variant="caption" tone="muted" style={styles.stepNumber} tabular>
                    {position + 1}
                  </Text>
                  <Text variant="body" style={styles.grow}>
                    {step}
                  </Text>
                </View>
              ))}
            </Card>
          ) : null}

          {primary.length > 0 && (
            <Card style={styles.section}>
              <Text variant="overline" tone="muted">
                MUSCLES
              </Text>
              <Text variant="body">{primary.map((muscle) => muscle.name).join(", ")}</Text>
              {secondary.length > 0 && (
                <Text variant="caption" tone="muted">
                  Also: {secondary.map((muscle) => muscle.name).join(", ")}
                </Text>
              )}
            </Card>
          )}
        </View>
      </ScrollView>

      <View style={[styles.footer, { borderTopColor: theme.border }]}>
        <Button label={t("common.done")} style={styles.grow} onPress={() => router.back()} />
      </View>
    </Screen>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  const theme = useTheme();
  return (
    <View style={[styles.chip, { borderColor: theme.border }]}>
      <Text variant="caption" tone="secondary">
        {children}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: space.xxl },
  body: { padding: space.lg, gap: space.md },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md },
  titleRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  grow: { flex: 1 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.xs },
  chip: {
    minHeight: 28,
    justifyContent: "center",
    paddingHorizontal: space.sm,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  section: { gap: space.sm },
  step: { flexDirection: "row", gap: space.sm },
  stepNumber: { width: 18, textAlign: "center" },
  footer: {
    flexDirection: "row",
    padding: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
});
