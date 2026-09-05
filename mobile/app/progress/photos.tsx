import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { Camera, TriangleAlert } from "lucide-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Screen } from "@/components/ui/screen";
import { Text } from "@/components/ui/text";
import {
  defaultPair,
  type Photo,
  type PhotoPose,
  photoKeys,
  photosApi,
  POSES,
  spanLabel,
  weightDeltaLabel,
} from "@/features/progress/photos-api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * A private photo timeline, and a comparison of any two.
 *
 * The comparison is the point. A grid of photos is a grid; the same two photos side by
 * side with the months between them written underneath is the only view in the product
 * that shows a change slow enough to have been invisible day to day.
 *
 * These photos appear here and nowhere else — never on the dashboard, never in a share
 * card, never as a background. They are the most sensitive images the product holds.
 */
export default function ProgressPhotosScreen() {
  const t = useTranslate();
  const theme = useTheme();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [pose, setPose] = useState<PhotoPose>("front");
  const [uploadError, setUploadError] = useState<string | null>(null);

  const photos = useQuery({
    queryKey: photoKeys.list(pose),
    queryFn: () => photosApi.list(pose),
  });

  const items = useMemo(() => photos.data ?? [], [photos.data]);
  const ready = useMemo(() => items.filter((photo) => photo.isReady), [items]);

  const upload = useMutation({
    mutationFn: (asset: ImagePicker.ImagePickerAsset) =>
      photosApi.upload(
        {
          uri: asset.uri,
          mimeType: asset.mimeType ?? "image/jpeg",
          fileSize: asset.fileSize,
        },
        { pose },
      ),
    onSuccess: () => {
      setUploadError(null);
      void queryClient.invalidateQueries({ queryKey: photoKeys.all });
    },
    onError: (error: Error) => setUploadError(error.message),
  });

  const pick = async () => {
    // The library, not the camera. Somebody taking a progress photo props the phone
    // against something and uses the timer — asking them to shoot inside our app means
    // holding it, which is the one framing that cannot be repeated next month.
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(t("photos.permissionTitle"), t("photos.permissionBody"));
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 1,
      // No editing step. A cropped photo is not comparable with an uncropped one, and
      // the comparison is the entire value of the feature.
      allowsEditing: false,
    });
    if (result.canceled || !result.assets[0]) return;
    upload.mutate(result.assets[0]);
  };

  return (
    <Screen edges={["top"]} padded={false}>
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <Text variant="h3" style={styles.grow}>
          {t("photos.title")}
        </Text>
        <Pressable onPress={() => router.back()} accessibilityRole="button" hitSlop={8}>
          <Text tone="accent">{t("common.done")}</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <Text variant="caption" tone="muted">
          {t("photos.privacyNote")}
        </Text>

        <View style={[styles.poses, { backgroundColor: theme.surfaceWell }]}>
          {POSES.map((option) => (
            <Pressable
              key={option}
              onPress={() => setPose(option)}
              accessibilityRole="tab"
              accessibilityState={{ selected: pose === option }}
              style={[
                styles.pose,
                pose === option && { backgroundColor: theme.accent },
              ]}
            >
              <Text
                variant="caption"
                tone={pose === option ? "default" : "muted"}
                style={pose === option ? { color: theme.accentInk } : undefined}
              >
                {t(`photos.pose.${option}` as "photos.pose.front")}
              </Text>
            </Pressable>
          ))}
        </View>

        <Button label={t("photos.add")} onPress={pick} loading={upload.isPending} />

        {uploadError && (
          <Text variant="caption" tone="critical" accessibilityRole="alert">
            {uploadError}
          </Text>
        )}

        {photos.isLoading ? (
          <ActivityIndicator color={theme.textMuted} style={styles.spinner} />
        ) : items.length === 0 ? (
          <Card style={styles.empty}>
            <Camera size={24} color={theme.textMuted} />
            <Text variant="body" tone="muted" style={styles.centre}>
              {t("photos.empty")}
            </Text>
          </Card>
        ) : (
          <>
            {ready.length >= 2 && <Comparison photos={ready} />}
            <Grid photos={items} />
          </>
        )}
      </ScrollView>
    </Screen>
  );
}

/**
 * Two photos side by side, oldest and newest by default.
 *
 * Side by side rather than a draggable slider: a slider needs a precise drag on a
 * surface that is already scrolling, and on a phone that fight is lost every time. Two
 * halves with the dates under them say the same thing and stay legible.
 */
function Comparison({ photos }: { photos: Photo[] }) {
  const t = useTranslate();
  const theme = useTheme();
  const { width } = useWindowDimensions();
  const pair = defaultPair(photos);

  const comparison = useQuery({
    queryKey: photoKeys.comparison(pair?.[0].id ?? "", pair?.[1].id ?? ""),
    queryFn: () => photosApi.compare(pair![0].id, pair![1].id),
    enabled: Boolean(pair),
  });

  if (!pair) return null;

  const data = comparison.data;
  const half = (width - space.lg * 2 - space.sm) / 2;
  const delta = weightDeltaLabel(data?.weightDeltaKg ?? null);

  return (
    <Card style={styles.comparison}>
      <Text variant="caption" tone="muted">
        {data ? `${spanLabel(data.daysBetween)} ${t("photos.apart")}` : t("common.loading")}
        {delta ? ` · ${delta}` : ""}
      </Text>

      {data && !data.posesMatch && (
        <View style={styles.warning}>
          <TriangleAlert size={14} color={theme.warning} />
          <Text variant="caption" tone="muted" style={styles.grow}>
            {t("photos.poseMismatch")}
          </Text>
        </View>
      )}

      <View style={styles.sideBySide}>
        {[data?.earlier, data?.later].map((photo, index) => (
          <View key={index} style={{ width: half }}>
            <View
              style={[
                styles.frame,
                { width: half, height: half * 1.33, backgroundColor: theme.surfaceWell },
              ]}
            >
              {photo?.url && (
                <Image
                  source={{ uri: photo.url }}
                  style={styles.image}
                  contentFit="cover"
                  accessibilityLabel={t("photos.photoFrom", { date: photo.localDate })}
                />
              )}
            </View>
            <Text variant="caption" tone="muted" tabular style={styles.centre}>
              {photo?.localDate ?? ""}
            </Text>
          </View>
        ))}
      </View>
    </Card>
  );
}

function Grid({ photos }: { photos: Photo[] }) {
  const t = useTranslate();
  const theme = useTheme();
  const queryClient = useQueryClient();
  const { width } = useWindowDimensions();

  // Three across, which is the most that keeps a face recognisable on a phone.
  const size = (width - space.lg * 2 - space.sm * 2) / 3;

  const remove = useMutation({
    mutationFn: (photoId: string) => photosApi.remove(photoId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: photoKeys.all }),
  });

  const confirmDelete = (photo: Photo) => {
    Alert.alert(t("photos.deleteTitle"), t("photos.deleteBody"), [
      { text: t("common.cancel"), style: "cancel" },
      {
        text: t("common.delete"),
        style: "destructive",
        onPress: () => remove.mutate(photo.id),
      },
    ]);
  };

  return (
    <View style={styles.grid}>
      {photos.map((photo) => (
        <Pressable
          key={photo.id}
          onLongPress={() => confirmDelete(photo)}
          accessibilityRole="image"
          accessibilityLabel={t("photos.photoFrom", { date: photo.localDate })}
          accessibilityHint={t("photos.deleteHint")}
          style={[
            styles.tile,
            { width: size, height: size * 1.33, backgroundColor: theme.surfaceWell },
          ]}
        >
          {photo.thumbnailUrl ? (
            <Image source={{ uri: photo.thumbnailUrl }} style={styles.image} contentFit="cover" />
          ) : (
            // A photo has a state and it is shown, rather than a broken image or a
            // spinner that never resolves.
            <View style={styles.pending}>
              {photo.processingStatus === "failed" ? (
                <TriangleAlert size={16} color={theme.critical} />
              ) : (
                <ActivityIndicator color={theme.textMuted} />
              )}
              <Text variant="caption" tone="muted" style={styles.centre}>
                {photo.processingStatus === "failed"
                  ? t("photos.failed")
                  : t("photos.processing")}
              </Text>
            </View>
          )}
        </Pressable>
      ))}
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
  content: { padding: space.lg, gap: space.md, paddingBottom: space.xxl },
  poses: { flexDirection: "row", gap: space.xs, padding: space.xs, borderRadius: radius.md },
  pose: {
    flex: 1,
    alignItems: "center",
    paddingVertical: space.sm,
    borderRadius: radius.sm,
  },
  spinner: { marginTop: space.xl },
  empty: { alignItems: "center", gap: space.sm, paddingVertical: space.xl },
  centre: { textAlign: "center" },
  comparison: { gap: space.sm },
  warning: { flexDirection: "row", alignItems: "center", gap: space.xs },
  sideBySide: { flexDirection: "row", gap: space.sm },
  frame: { borderRadius: radius.md, overflow: "hidden" },
  image: { width: "100%", height: "100%" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  tile: { borderRadius: radius.md, overflow: "hidden" },
  pending: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.xs, padding: space.sm },
});
