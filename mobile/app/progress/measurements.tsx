import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  MEASUREMENT_SITES,
  type MeasurementSite,
  progressApi,
  progressKeys,
  SITE_LABELS,
} from "@/features/progress/api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, type, useTheme } from "@/theme";

/**
 * Record body measurements.
 *
 * Every site is optional and only what is filled in gets sent — the server keeps the
 * previous value for anything omitted. That matters because almost nobody measures all
 * ten sites in one sitting, and a form that demanded them would be abandoned halfway and
 * record nothing at all.
 *
 * The last recorded value is shown as the placeholder rather than pre-filled into the
 * field: pre-filling would let somebody submit last month's numbers as this month's
 * without noticing.
 */
export default function MeasurementsScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [values, setValues] = useState<Partial<Record<MeasurementSite, string>>>({});
  const [saving, setSaving] = useState(false);

  const history = useQuery({
    queryKey: progressKeys.measurements(),
    queryFn: progressApi.measurements,
  });

  const latest = history.data?.[0]?.sites ?? {};

  const filled = MEASUREMENT_SITES.filter((site) => {
    const raw = values[site];
    return raw !== undefined && raw.trim() !== "";
  });

  const onSave = async () => {
    if (filled.length === 0 || saving) return;

    const payload: Partial<Record<MeasurementSite, number>> = {};
    for (const site of filled) {
      const parsed = Number((values[site] ?? "").replace(",", "."));
      // Silently dropping an unparseable entry would record a measurement session that
      // is missing the one site the user came to log.
      if (!Number.isFinite(parsed) || parsed <= 0) {
        Alert.alert(t("progress.checkValue"), t("progress.notANumber"));
        return;
      }
      payload[site] = parsed;
    }

    setSaving(true);
    try {
      await progressApi.logMeasurement(payload);
      await queryClient.invalidateQueries({ queryKey: progressKeys.all });
      router.back();
    } catch (error) {
      console.warn("could not save measurements", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setSaving(false);
    }
  };

  const canSave = filled.length > 0 && !saving;

  return (
    <Screen edges={["top"]} padded={false}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.grow}
      >
        <View style={[styles.header, { borderBottomColor: theme.border }]}>
          <Pressable onPress={() => router.back()} accessibilityRole="button" style={styles.action}>
            <Text tone="accent">{t("common.cancel")}</Text>
          </Pressable>
          <Text variant="h3" style={styles.title} numberOfLines={1}>
            {t("progress.measurements")}
          </Text>
          <Pressable
            onPress={() => void onSave()}
            disabled={!canSave}
            accessibilityRole="button"
            accessibilityState={{ disabled: !canSave }}
            style={styles.action}
          >
            <Text tone={canSave ? "accent" : "muted"}>{t("common.save")}</Text>
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text variant="caption" tone="muted">
            {t("progress.onlyWhatYouMeasured")}
          </Text>

          <Card style={styles.card}>
            {MEASUREMENT_SITES.map((site) => (
              <View key={site} style={styles.row}>
                <Text variant="body" style={styles.grow}>
                  {SITE_LABELS[site]}
                </Text>
                <TextInput
                  value={values[site] ?? ""}
                  onChangeText={(text) => setValues((current) => ({ ...current, [site]: text }))}
                  keyboardType="decimal-pad"
                  selectTextOnFocus
                  placeholder={latest[site] ? Number(latest[site]).toFixed(1) : "—"}
                  placeholderTextColor={theme.textMuted}
                  accessibilityLabel={t("progress.centimetres", { name: SITE_LABELS[site] })}
                  style={[
                    styles.field,
                    { color: theme.text, backgroundColor: theme.surfaceWell },
                  ]}
                />
                <Text variant="caption" tone="muted" style={styles.unit}>
                  cm
                </Text>
              </View>
            ))}
          </Card>
        </ScrollView>
      </KeyboardAvoidingView>
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
  title: { flex: 1, textAlign: "center" },
  action: { minWidth: 64, paddingVertical: space.sm },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  card: { gap: space.sm },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  grow: { flex: 1 },
  field: {
    width: 84,
    height: 40,
    borderRadius: radius.sm,
    textAlign: "center",
    fontSize: type.body.fontSize,
    fontVariant: ["tabular-nums"],
  },
  unit: { width: 22 },
});
