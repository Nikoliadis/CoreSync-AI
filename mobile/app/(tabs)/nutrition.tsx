import { useQuery } from "@tanstack/react-query";
import { ScrollView, StyleSheet, View } from "react-native";

import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import { dashboardApi, dashboardKeys } from "@/features/dashboard/api";
import { useTranslate } from "@/lib/i18n";
import { space, useTheme } from "@/theme";

const MEALS = ["breakfast", "lunch", "dinner", "snack"] as const;
const round = (value: string | null | undefined) => Math.round(Number(value ?? 0));

export default function NutritionScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const diary = useQuery({ queryKey: dashboardKeys.diary(), queryFn: dashboardApi.diary });

  const byMeal = new Map<string, typeof entries>();
  const entries = diary.data?.entries ?? [];
  for (const meal of MEALS) byMeal.set(meal, []);
  for (const entry of entries) byMeal.get(entry.mealType)?.push(entry);

  return (
    <Screen edges={["top"]} padded={false}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text variant="h1">{t("nutrition.diary")}</Text>

        {MEALS.map((meal) => {
          const items = byMeal.get(meal) ?? [];
          const total = items.reduce((sum, item) => sum + round(item.macros.calories), 0);
          return (
            <Card key={meal} style={styles.card}>
              <View style={styles.header}>
                <Text variant="h3">{t(`nutrition.${meal}` as never)}</Text>
                <Text variant="caption" tone="muted" tabular>
                  {total} kcal
                </Text>
              </View>

              {items.length === 0 ? (
                <Text variant="caption" tone="muted">
                  {t("nutrition.nothingLogged")}
                </Text>
              ) : (
                items.map((item) => (
                  <View
                    key={item.id}
                    style={[styles.entry, { borderTopColor: theme.border }]}
                  >
                    <Text numberOfLines={1} style={styles.name}>
                      {item.displayName}
                    </Text>
                    <Text tone="secondary" tabular>
                      {round(item.macros.calories)}
                    </Text>
                  </View>
                ))
              )}
            </Card>
          );
        })}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  card: { gap: space.sm },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  entry: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: space.md,
    paddingVertical: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  name: { flex: 1 },
});
