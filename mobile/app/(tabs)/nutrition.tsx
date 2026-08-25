import { useFocusEffect, useRouter } from "expo-router";
import {
  ChevronLeft,
  ChevronRight,
  CloudOff,
  Droplet,
  Plus,
  Trash2,
} from "lucide-react-native";
import { useCallback, useState } from "react";
import {
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  MEAL_LABEL_KEYS,
  MEAL_ORDER,
  type DiaryEntry,
  type MealType,
  grams,
  kcal,
  portion,
} from "@/features/nutrition/api";
import { friendlyDate, isFuture, localToday, shiftDate } from "@/features/nutrition/dates";
import { usePickedFood } from "@/features/nutrition/picked-food";
import { useDiary } from "@/features/nutrition/use-diary";
import { useTranslate, type MessageKey } from "@/lib/i18n";
import { HIT_SIZE, radius, space, useTheme } from "@/theme";

const WATER_INCREMENTS = [250, 500];
const WATER_GOAL_ML = 2500;

/**
 * The diary.
 *
 * Reads work offline from cache and say so. Writes need a connection — the nutrition
 * endpoints mint entry ids server-side and there is no sync endpoint, so a queued write
 * replayed later would duplicate rather than reconcile. Refusing is honest; silently
 * logging somebody's dinner twice is not.
 */
export default function NutritionScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const [day, setDay] = useState(localToday);
  const [editing, setEditing] = useState<DiaryEntry | null>(null);

  const view = useDiary(day);
  const { logFood } = view;
  const consumePicked = usePickedFood((state) => state.consume);

  // The food search hands its choice back here. Consumed on focus rather than during
  // render — logging from a render body fires again on every re-render — and `consume`
  // clears as it reads, so returning to this tab for any other reason cannot re-log.
  useFocusEffect(
    useCallback(() => {
      const picked = consumePicked();
      if (!picked) return;
      void logFood({
        foodId: picked.foodId,
        mealType: picked.mealType,
        quantity: picked.quantity,
        servingId: picked.servingId,
      });
    }, [consumePicked, logFood]),
  );

  const diary = view.diary;
  const target = diary?.targets ? kcal(diary.targets.calories) : null;
  const eaten = kcal(diary?.totals.calories);

  const byMeal = new Map<MealType, DiaryEntry[]>();
  for (const meal of MEAL_ORDER) byMeal.set(meal, []);
  for (const entry of diary?.entries ?? []) byMeal.get(entry.mealType)?.push(entry);

  const onDelete = (entry: DiaryEntry) => {
    Alert.alert(entry.displayName, "Remove this from your diary?", [
      { text: t("common.cancel"), style: "cancel" },
      {
        text: t("common.delete"),
        style: "destructive",
        onPress: () => void view.deleteEntry(entry.id),
      },
    ]);
  };

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <Pressable
          onPress={() => setDay(shiftDate(day, -1))}
          accessibilityRole="button"
          accessibilityLabel="Previous day"
          style={styles.arrow}
        >
          <ChevronLeft size={22} color={theme.textMuted} />
        </Pressable>

        <Text variant="h3">{friendlyDate(day)}</Text>

        <Pressable
          onPress={() => setDay(shiftDate(day, 1))}
          // Logging ahead is meaningless, and an endlessly forward-scrolling diary is a
          // way to get lost in empty days.
          disabled={isFuture(shiftDate(day, 1))}
          accessibilityRole="button"
          accessibilityLabel="Next day"
          accessibilityState={{ disabled: isFuture(shiftDate(day, 1)) }}
          style={[styles.arrow, { opacity: isFuture(shiftDate(day, 1)) ? 0.3 : 1 }]}
        >
          <ChevronRight size={22} color={theme.textMuted} />
        </Pressable>
      </View>

      {view.servedFromCache && (
        <Banner icon={<CloudOff size={14} color={theme.textMuted} />}>
          {t("common.offline")}
        </Banner>
      )}

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={view.isLoading}
            onRefresh={view.refetch}
            tintColor={theme.textMuted}
          />
        }
      >
        {view.isError && !diary ? (
          <Card style={styles.centre}>
            <Text tone="secondary">{t("common.errorTitle")}</Text>
            <Button label={t("common.retry")} variant="ghost" onPress={view.refetch} />
          </Card>
        ) : (
          <>
            <Card style={styles.summary}>
              <Text variant="overline" tone="muted">
                {t("home.todaysCalories").toUpperCase()}
              </Text>
              <View style={styles.calorieRow}>
                <Text variant="display" tabular>
                  {eaten}
                </Text>
                {target !== null ? (
                  <Text variant="body" tone="secondary" style={styles.flexible}>
                    {t("nutrition.caloriesLeft", { count: Math.max(target - eaten, 0) })}
                  </Text>
                ) : (
                  // No target is not a failure state — there is nothing to be over or
                  // under, and a red bar would invent a judgement nobody asked for.
                  <Text variant="caption" tone="muted" style={styles.flexible}>
                    {t("nutrition.noTarget")}
                  </Text>
                )}
              </View>

              <View style={styles.macros}>
                <MacroBar
                  label={t("home.protein")}
                  value={grams(diary?.totals.proteinG)}
                  goal={diary?.targets ? grams(diary.targets.proteinG) : null}
                  color={theme.chart[0] ?? theme.accent}
                />
                <MacroBar
                  label={t("home.carbs")}
                  value={grams(diary?.totals.carbsG)}
                  goal={diary?.targets ? grams(diary.targets.carbsG) : null}
                  color={theme.chart[1] ?? theme.accent}
                />
                <MacroBar
                  label={t("home.fat")}
                  value={grams(diary?.totals.fatG)}
                  goal={diary?.targets ? grams(diary.targets.fatG) : null}
                  color={theme.chart[2] ?? theme.accent}
                />
              </View>
            </Card>

            <Card style={styles.water}>
              <View style={styles.waterHead}>
                <Text variant="overline" tone="muted">
                  {t("home.water").toUpperCase()}
                </Text>
                <Text variant="caption" tone="muted" tabular>
                  {grams(diary?.waterMl)} / {WATER_GOAL_ML} ml
                </Text>
              </View>
              <Track
                value={grams(diary?.waterMl)}
                goal={WATER_GOAL_ML}
                color={theme.chart[1] ?? theme.accent}
              />
              <View style={styles.chips}>
                {WATER_INCREMENTS.map((amount) => (
                  <Pressable
                    key={amount}
                    disabled={view.isMutating}
                    onPress={() => void view.logWater(amount)}
                    accessibilityRole="button"
                    accessibilityLabel={`Add ${amount} millilitres of water`}
                    style={[styles.chip, { borderColor: theme.border }]}
                  >
                    <Droplet size={14} color={theme.textMuted} />
                    <Text variant="caption" tone="secondary">
                      +{amount}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </Card>

            {MEAL_ORDER.map((meal) => {
              const entries = byMeal.get(meal) ?? [];
              const totals = diary?.byMeal.find((m) => m.mealType === meal);
              return (
                <Card key={meal} style={styles.meal}>
                  <View style={styles.mealHead}>
                    <Text variant="h3">{t(MEAL_LABEL_KEYS[meal] as MessageKey)}</Text>
                    <View style={styles.mealActions}>
                      <Text variant="caption" tone="muted" tabular>
                        {kcal(totals?.macros.calories)} kcal
                      </Text>
                      <Pressable
                        onPress={() =>
                          router.push({
                            pathname: "/nutrition/search",
                            params: { meal, date: day },
                          })
                        }
                        accessibilityRole="button"
                        accessibilityLabel={`Add to ${meal}`}
                        style={styles.add}
                      >
                        <Plus size={20} color={theme.accentText} />
                      </Pressable>
                    </View>
                  </View>

                  {entries.length === 0 ? (
                    <Text variant="caption" tone="muted" style={styles.empty}>
                      {t("nutrition.nothingLogged")}
                    </Text>
                  ) : (
                    entries.map((entry) => (
                      <Pressable
                        key={entry.id}
                        onPress={() => setEditing(entry)}
                        onLongPress={() => onDelete(entry)}
                        accessibilityRole="button"
                        accessibilityLabel={`${entry.displayName}, ${kcal(entry.macros.calories)} calories`}
                        accessibilityHint="Long press to remove"
                        style={[styles.entry, { borderTopColor: theme.border }]}
                      >
                        <View style={styles.entryText}>
                          <Text numberOfLines={1}>{entry.displayName}</Text>
                          <Text variant="caption" tone="muted" tabular>
                            {portion(entry.totalGrams)}g · P{grams(entry.macros.proteinG)}{" "}
                            C{grams(entry.macros.carbsG)} F{grams(entry.macros.fatG)}
                          </Text>
                        </View>
                        <Text tabular tone="secondary">
                          {kcal(entry.macros.calories)}
                        </Text>
                      </Pressable>
                    ))
                  )}
                </Card>
              );
            })}

            <Button
              label="Copy a previous day"
              variant="secondary"
              onPress={() =>
                router.push({ pathname: "/nutrition/copy", params: { date: day } })
              }
            />
          </>
        )}
      </ScrollView>

      {editing && (
        <EditEntrySheet
          entry={editing}
          onClose={() => setEditing(null)}
          onSave={async (quantity) => {
            await view.editEntry(editing.id, { quantity });
            setEditing(null);
          }}
          onDelete={() => {
            const target = editing;
            setEditing(null);
            onDelete(target);
          }}
        />
      )}
    </Screen>
  );
}

function Banner({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  const theme = useTheme();
  return (
    <View style={[styles.banner, { backgroundColor: theme.surfaceWell }]}>
      {icon}
      <Text variant="caption" tone="muted" style={styles.flexible}>
        {children}
      </Text>
    </View>
  );
}

function MacroBar({
  label,
  value,
  goal,
  color,
}: {
  label: string;
  value: number;
  goal: number | null;
  color: string;
}) {
  return (
    <View style={styles.macro}>
      <View style={styles.macroHead}>
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
        <Text variant="caption" tone="muted" tabular>
          {value}
          {goal ? ` / ${goal}` : ""} g
        </Text>
      </View>
      <Track value={value} goal={goal} color={color} />
    </View>
  );
}

function Track({
  value,
  goal,
  color,
}: {
  value: number;
  goal: number | null;
  color: string;
}) {
  const theme = useTheme();
  const pct = goal && goal > 0 ? Math.min((value / goal) * 100, 100) : 0;
  return (
    <View
      style={[styles.track, { backgroundColor: theme.surfaceWell }]}
      accessibilityRole="progressbar"
      accessibilityValue={{ now: value, min: 0, max: goal ?? undefined }}
    >
      <View style={[styles.fill, { width: `${pct}%`, backgroundColor: color }]} />
    </View>
  );
}

/** Amount only. Anything more belongs on the food, not on one logged portion of it. */
function EditEntrySheet({
  entry,
  onClose,
  onSave,
  onDelete,
}: {
  entry: DiaryEntry;
  onClose: () => void;
  onSave: (quantity: number) => Promise<void>;
  onDelete: () => void;
}) {
  const t = useTranslate();
  const theme = useTheme();
  const [quantity, setQuantity] = useState(portion(entry.quantity));
  const [saving, setSaving] = useState(false);

  const amount = Number(quantity) || 0;

  return (
    <View style={[styles.sheet, { backgroundColor: theme.surfaceRaised, borderTopColor: theme.border }]}>
      <Text variant="h3" numberOfLines={1}>
        {entry.displayName}
      </Text>
      <Text variant="caption" tone="muted">
        {entry.servingId ? "Servings" : "Grams"}
      </Text>
      <View style={styles.sheetRow}>
        <Pressable
          onPress={onDelete}
          accessibilityRole="button"
          accessibilityLabel={t("common.delete")}
          style={[styles.sheetIcon, { borderColor: theme.border }]}
        >
          <Trash2 size={18} color={theme.critical} />
        </Pressable>
        <QuantityField value={quantity} onChange={setQuantity} />
        <Button
          label={saving ? "…" : t("common.save")}
          size="sm"
          disabled={amount <= 0 || saving}
          onPress={() => {
            setSaving(true);
            void onSave(amount).finally(() => setSaving(false));
          }}
        />
      </View>
      <Button label={t("common.cancel")} variant="ghost" size="sm" onPress={onClose} />
    </View>
  );
}

function QuantityField({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const theme = useTheme();
  return (
    <TextInput
      value={value}
      onChangeText={onChange}
      keyboardType="decimal-pad"
      selectTextOnFocus
      autoFocus
      accessibilityLabel="Amount"
      style={[
        styles.quantity,
        { color: theme.text, backgroundColor: theme.surfaceWell },
      ]}
    />
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  arrow: {
    width: HIT_SIZE,
    height: HIT_SIZE,
    alignItems: "center",
    justifyContent: "center",
  },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { alignItems: "center", gap: space.md, paddingVertical: space.xl },
  summary: { gap: space.sm },
  calorieRow: { flexDirection: "row", alignItems: "baseline", gap: space.md },
  flexible: { flexShrink: 1 },
  macros: { gap: space.sm, marginTop: space.xs },
  macro: { gap: 4 },
  macroHead: { flexDirection: "row", justifyContent: "space-between" },
  track: { height: 6, borderRadius: radius.full, overflow: "hidden" },
  fill: { height: "100%", borderRadius: radius.full },
  water: { gap: space.sm },
  waterHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  chips: { flexDirection: "row", gap: space.sm, marginTop: space.xs },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.xs,
    minHeight: 36,
    paddingHorizontal: space.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  meal: { gap: space.xs },
  mealHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  mealActions: { flexDirection: "row", alignItems: "center", gap: space.sm },
  add: { width: HIT_SIZE, height: HIT_SIZE, alignItems: "center", justifyContent: "center" },
  empty: { paddingVertical: space.sm },
  entry: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: space.md,
    minHeight: 52,
    paddingVertical: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  entryText: { flex: 1, gap: 2 },
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    gap: space.sm,
    padding: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
  },
  sheetRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  sheetIcon: {
    width: HIT_SIZE,
    height: HIT_SIZE,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  quantity: {
    flex: 1,
    height: HIT_SIZE,
    borderRadius: radius.md,
    textAlign: "center",
    fontSize: 16,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
});
