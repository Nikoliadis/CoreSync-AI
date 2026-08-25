import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { BadgeCheck, Search, X } from "lucide-react-native";
import { useState } from "react";
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
  type Food,
  type MealType,
  kcal,
  nutritionApi,
  nutritionKeys,
  portion,
} from "@/features/nutrition/api";
import { usePickedFood } from "@/features/nutrition/picked-food";
import { useTranslate } from "@/lib/i18n";
import { useDebouncedValue } from "@/lib/utils/use-debounced-value";
import { HIT_SIZE, radius, space, type, useTheme } from "@/theme";

/**
 * Find a food and choose how much of it.
 *
 * Two steps, not one. Choosing *what* and choosing *how much* are different decisions,
 * and a quantity field on every row of a search result is unreadable on a phone.
 *
 * Search is diacritic-insensitive server-side, so `γιαουρτι` finds `Γιαούρτι` — nobody
 * types the tonos on a phone keyboard.
 */
export default function FoodSearchScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ meal?: string; date?: string }>();
  const meal = (params.meal ?? "snack") as MealType;

  const [term, setTerm] = useState("");
  const [selected, setSelected] = useState<Food | null>(null);
  const debounced = useDebouncedValue(term, 250);
  const query = debounced.trim();

  const results = useQuery({
    queryKey: nutritionKeys.search(query),
    queryFn: () => nutritionApi.search(query),
    enabled: query.length > 0,
  });

  // The empty state is a real feature, not a placeholder: most logging is re-logging.
  const recent = useQuery({
    queryKey: nutritionKeys.recent(),
    queryFn: nutritionApi.recent,
    enabled: query.length === 0,
  });

  const showing = query.length > 0 ? results : recent;
  const items = showing.data?.items ?? [];

  if (selected) {
    return (
      <PortionScreen
        food={selected}
        meal={meal}
        onBack={() => setSelected(null)}
        onConfirm={(quantity, servingId) => {
          usePickedFood.getState().pick({
            foodId: selected.id,
            mealType: meal,
            quantity,
            servingId,
          });
          // Straight back to the diary, which logs it on focus. No confirmation screen —
          // the tap on "Add" is the confirmation.
          router.back();
        }}
      />
    );
  }

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <View style={[styles.searchBox, { backgroundColor: theme.surfaceWell }]}>
          <Search size={18} color={theme.textMuted} />
          <TextInput
            autoFocus
            value={term}
            onChangeText={setTerm}
            placeholder={t("nutrition.searchFoods")}
            placeholderTextColor={theme.textMuted}
            accessibilityLabel={t("nutrition.searchFoods")}
            returnKeyType="search"
            style={[styles.input, { color: theme.text }]}
          />
          {term.length > 0 && (
            <Pressable
              onPress={() => setTerm("")}
              accessibilityRole="button"
              accessibilityLabel={t("common.cancel")}
              hitSlop={8}
            >
              <X size={18} color={theme.textMuted} />
            </Pressable>
          )}
        </View>
        <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.cancel}>
          <Text tone="accent">{t("common.cancel")}</Text>
        </Pressable>
      </View>

      {showing.isLoading ? (
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      ) : showing.isError ? (
        <View style={styles.centre}>
          <Text tone="secondary">{t("common.errorTitle")}</Text>
          <Button
            label={t("common.retry")}
            variant="ghost"
            onPress={() => void showing.refetch()}
          />
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(food) => food.id}
          keyboardShouldPersistTaps="handled"
          initialNumToRender={12}
          windowSize={9}
          removeClippedSubviews
          ListHeaderComponent={
            query.length === 0 && items.length > 0 ? (
              <Text variant="overline" tone="muted" style={styles.sectionLabel}>
                {t("nutrition.recent").toUpperCase()}
              </Text>
            ) : null
          }
          ListEmptyComponent={
            <View style={styles.centre}>
              <Text tone="secondary">
                {query.length > 0
                  ? "Nothing matched. Try a shorter word."
                  : t("nutrition.nothingLogged")}
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() => setSelected(item)}
              accessibilityRole="button"
              accessibilityLabel={`${item.name}, ${kcal(item.caloriesPer100g)} calories per 100 ${item.isLiquid ? "millilitres" : "grams"}`}
              style={({ pressed }) => [
                styles.row,
                { borderBottomColor: theme.border, opacity: pressed ? 0.6 : 1 },
              ]}
            >
              <View style={styles.rowText}>
                <View style={styles.rowTitle}>
                  <Text numberOfLines={1} style={styles.name}>
                    {item.name}
                  </Text>
                  {item.isVerified && (
                    <BadgeCheck size={14} color={theme.accentText} />
                  )}
                </View>
                <Text variant="caption" tone="muted" tabular>
                  {kcal(item.caloriesPer100g)} kcal · {t("nutrition.perHundred", {
                    unit: item.isLiquid ? "ml" : "g",
                  })}
                </Text>
              </View>
            </Pressable>
          )}
        />
      )}
    </Screen>
  );
}

/** Step two: how much. Prefilled from the food's default serving where it has one. */
function PortionScreen({
  food,
  meal,
  onBack,
  onConfirm,
}: {
  food: Food;
  meal: MealType;
  onBack: () => void;
  onConfirm: (quantity: number, servingId: string | null) => void;
}) {
  const t = useTranslate();
  const theme = useTheme();

  const defaultServing = food.servings.find((s) => s.isDefault) ?? food.servings[0] ?? null;
  const [servingId, setServingId] = useState<string | null>(defaultServing?.id ?? null);
  const [quantity, setQuantity] = useState(defaultServing ? "1" : "100");

  const serving = food.servings.find((s) => s.id === servingId) ?? null;
  const amount = Number(quantity.replace(",", ".")) || 0;
  const totalGrams = serving ? amount * Number(serving.grams) : amount;
  const preview = Math.round((totalGrams / 100) * Number(food.caloriesPer100g));
  const unit = food.isLiquid ? "ml" : "g";

  return (
    <Screen edges={["top", "bottom"]}>
      <View style={styles.portion}>
        <Text variant="h2" numberOfLines={2}>
          {food.name}
        </Text>

        <TextInput
          autoFocus
          value={quantity}
          onChangeText={setQuantity}
          keyboardType="decimal-pad"
          selectTextOnFocus
          accessibilityLabel="Amount"
          style={[styles.amount, { color: theme.text, backgroundColor: theme.surfaceWell }]}
        />

        {food.servings.length > 0 && (
          <View style={styles.chips}>
            {food.servings.map((option) => (
              <Chip
                key={option.id}
                active={servingId === option.id}
                onPress={() => {
                  setServingId(option.id);
                  setQuantity("1");
                }}
              >
                {option.label} ({portion(option.grams)}
                {unit})
              </Chip>
            ))}
            <Chip
              active={servingId === null}
              onPress={() => {
                setServingId(null);
                setQuantity("100");
              }}
            >
              {unit}
            </Chip>
          </View>
        )}

        <Text variant="body" tone="secondary">
          <Text variant="display" tabular>
            {preview}
          </Text>{" "}
          kcal · {portion(String(totalGrams))}
          {unit}
        </Text>
      </View>

      <View style={styles.actions}>
        <Button label={t("common.cancel")} variant="ghost" onPress={onBack} />
        <Button
          label={`${t("nutrition.addFood")} — ${t(`nutrition.${meal}` as never)}`}
          disabled={amount <= 0}
          onPress={() => onConfirm(amount, servingId)}
        />
      </View>
    </Screen>
  );
}

function Chip({
  active,
  onPress,
  children,
}: {
  active: boolean;
  onPress: () => void;
  children: React.ReactNode;
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
        {children}
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
  input: { flex: 1, fontSize: type.body.fontSize },
  cancel: { minHeight: HIT_SIZE, justifyContent: "center", paddingHorizontal: space.xs },
  centre: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: space.md,
    padding: space.xl,
  },
  sectionLabel: { paddingHorizontal: space.lg, paddingVertical: space.sm },
  row: {
    minHeight: 60,
    justifyContent: "center",
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowText: { gap: 2 },
  rowTitle: { flexDirection: "row", alignItems: "center", gap: space.xs },
  name: { flexShrink: 1 },
  portion: { flex: 1, justifyContent: "center", gap: space.lg },
  amount: {
    height: 64,
    borderRadius: radius.md,
    textAlign: "center",
    fontSize: 28,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: space.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  actions: { gap: space.sm, paddingBottom: space.lg },
});
