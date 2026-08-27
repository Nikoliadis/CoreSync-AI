import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
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
  ACTIVITY_LABELS,
  ACTIVITY_LEVELS,
  EXPERIENCE_LABELS,
  EXPERIENCE_LEVELS,
  settingsApi,
  settingsKeys,
} from "@/features/settings/api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, type, useTheme } from "@/theme";

/**
 * The facts the targets are computed from.
 *
 * Height, age, activity and experience are not vanity fields — Mifflin-St Jeor needs all
 * of them, so a wrong height means wrong calories every day until it is corrected. That
 * is why this is a real screen rather than a row buried in settings.
 */
export default function ProfileEditScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const me = useQuery({ queryKey: settingsKeys.me(), queryFn: settingsApi.me });

  const [displayName, setDisplayName] = useState("");
  const [height, setHeight] = useState("");
  const [bio, setBio] = useState("");
  const [activity, setActivity] = useState<string>("moderate");
  const [experience, setExperience] = useState<string>("beginner");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const profile = me.data?.profile;
    if (!profile || loaded) return;
    setDisplayName(profile.displayName);
    setHeight(profile.heightCm ? String(Math.round(Number(profile.heightCm))) : "");
    setBio(profile.bio ?? "");
    setActivity(profile.activityLevel);
    setExperience(profile.experienceLevel);
    // Once only: re-running on refetch would discard edits in progress.
    setLoaded(true);
  }, [me.data, loaded]);

  const onSave = async () => {
    if (saving) return;
    const name = displayName.trim();
    if (name.length === 0) {
      Alert.alert(t("profileEdit.nameRequired"), t("profileEdit.nameEmpty"));
      return;
    }

    const parsedHeight = height.trim() === "" ? null : Number(height.replace(",", "."));
    if (parsedHeight !== null && (!Number.isFinite(parsedHeight) || parsedHeight <= 0)) {
      Alert.alert(t("profileEdit.checkHeight"), t("profileEdit.heightNotANumber"));
      return;
    }

    setSaving(true);
    try {
      await settingsApi.updateProfile({
        displayName: name,
        heightCm: parsedHeight,
        bio: bio.trim() === "" ? null : bio.trim(),
        activityLevel: activity,
        experienceLevel: experience,
      });
      await queryClient.invalidateQueries({ queryKey: settingsKeys.all });
      // Targets are derived from these, so a stale copy would show calories computed
      // from the old height until something else happened to refresh them.
      await queryClient.invalidateQueries({ queryKey: ["goals"] });
      router.back();
    } catch (error) {
      console.warn("could not save profile", error);
      Alert.alert(t("common.errorTitle"), t("common.errorBody"));
    } finally {
      setSaving(false);
    }
  };

  if (me.isLoading) {
    return (
      <Screen edges={["top", "bottom"]}>
        <View style={styles.centre}>
          <ActivityIndicator color={theme.textMuted} />
        </View>
      </Screen>
    );
  }

  const canSave = displayName.trim().length > 0 && !saving;

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
          <Text variant="h3" style={styles.title}>
            {t("profileEdit.title")}
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
          <Card style={styles.card}>
            <Field
              label={t("profileEdit.displayName")}
              value={displayName}
              onChangeText={setDisplayName}
              placeholder={t("profileEdit.yourName")}
            />
            <Field
              label={t("profileEdit.height")}
              value={height}
              onChangeText={setHeight}
              placeholder="—"
              keyboardType="decimal-pad"
              unit="cm"
            />
          </Card>

          <Card style={styles.card}>
            <Text variant="overline" tone="muted">
              {t("profileEdit.activity")}
            </Text>
            <Text variant="caption" tone="muted">
              {t("profileEdit.activityDetail")}
            </Text>
            <View style={styles.chips}>
              {ACTIVITY_LEVELS.map((level) => (
                <Chip
                  key={level}
                  label={ACTIVITY_LABELS[level] ?? level}
                  active={activity === level}
                  onPress={() => setActivity(level)}
                />
              ))}
            </View>
          </Card>

          <Card style={styles.card}>
            <Text variant="overline" tone="muted">
              {t("profileEdit.experience")}
            </Text>
            <View style={styles.chips}>
              {EXPERIENCE_LEVELS.map((level) => (
                <Chip
                  key={level}
                  label={EXPERIENCE_LABELS[level] ?? level}
                  active={experience === level}
                  onPress={() => setExperience(level)}
                />
              ))}
            </View>
          </Card>

          <Card style={styles.card}>
            <Text variant="overline" tone="muted">
              {t("profileEdit.bio")}
            </Text>
            <TextInput
              value={bio}
              onChangeText={setBio}
              placeholder={t("profileEdit.optional")}
              placeholderTextColor={theme.textMuted}
              accessibilityLabel={t("profileEdit.bio")}
              multiline
              maxLength={500}
              style={[styles.bio, { color: theme.text, backgroundColor: theme.surfaceWell }]}
            />
          </Card>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

function Field({
  label,
  value,
  onChangeText,
  placeholder,
  keyboardType,
  unit,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  keyboardType?: "decimal-pad";
  unit?: string;
}) {
  const theme = useTheme();
  return (
    <View style={styles.row}>
      <Text variant="body" style={styles.grow}>
        {label}
      </Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.textMuted}
        keyboardType={keyboardType}
        accessibilityLabel={label}
        style={[styles.field, { color: theme.text, backgroundColor: theme.surfaceWell }]}
      />
      {unit ? (
        <Text variant="caption" tone="muted" style={styles.unit}>
          {unit}
        </Text>
      ) : null}
    </View>
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
      accessibilityRole="radio"
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
    padding: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: { flex: 1, textAlign: "center" },
  action: { minWidth: 64, paddingVertical: space.sm },
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
  grow: { flex: 1 },
  card: { gap: space.sm },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  field: {
    width: 140,
    height: 40,
    paddingHorizontal: space.sm,
    borderRadius: radius.sm,
    textAlign: "right",
    fontSize: type.body.fontSize,
  },
  unit: { width: 22 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: space.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
  },
  bio: {
    minHeight: 80,
    padding: space.md,
    borderRadius: radius.sm,
    fontSize: type.body.fontSize,
    textAlignVertical: "top",
  },
});
