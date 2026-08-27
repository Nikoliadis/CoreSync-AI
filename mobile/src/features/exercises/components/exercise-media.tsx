import { Image } from "expo-image";
import { Dumbbell } from "lucide-react-native";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from "react-native";

import { Text } from "@/components/ui/text";
import { type ExerciseMedia } from "@/features/exercises/api";
import { useTranslate } from "@/lib/i18n";
import { radius, space, useTheme } from "@/theme";

/**
 * How a movement is performed, shown rather than described.
 *
 * A name and a muscle list tell an experienced lifter what to do and tell a beginner
 * nothing. This is the part of the catalogue that makes it usable by someone who has
 * never held a barbell, which is most of the people worth building for.
 *
 * `expo-image` rather than React Native's `Image`: it caches to disk across launches,
 * which matters because the same demonstration is opened over and over, and it decodes
 * animated WebP and GIF on both platforms without per-platform configuration.
 *
 * Degrades to a placeholder when an exercise has no media. That is the normal case for a
 * catalogue whose assets have not been imported, not an error worth showing.
 */
export function ExerciseMediaViewer({
  media,
  name,
}: {
  media: readonly ExerciseMedia[] | undefined;
  name: string;
}) {
  const t = useTranslate();
  const theme = useTheme();
  const { width } = useWindowDimensions();
  const [index, setIndex] = useState(0);

  // Full-bleed and 4:3, the aspect most demonstration photography is shot at. Letting it
  // size to the image would make the page jump as each one decodes.
  const frameWidth = width;
  const frameHeight = Math.round((frameWidth * 3) / 4);

  // Only what this component can actually render. A `video` row is an mp4 and needs a
  // player; showing it as an image would render a broken frame, which is worse than
  // leaving it out until the player exists.
  const showable = (media ?? []).filter(
    (item) => item.mediaType === "image" || item.mediaType === "animation",
  );

  if (showable.length === 0) {
    return (
      <View
        style={[
          styles.placeholder,
          { width: frameWidth, height: frameHeight, backgroundColor: theme.surfaceWell },
        ]}
      >
        <Dumbbell size={40} color={theme.textMuted} />
        <Text variant="caption" tone="muted">
          {t("exercises.noDemonstration")}
        </Text>
      </View>
    );
  }

  return (
    <View>
      <ScrollView
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={(event) => {
          const page = Math.round(event.nativeEvent.contentOffset.x / frameWidth);
          setIndex(page);
        }}
        style={{ width: frameWidth, height: frameHeight }}
      >
        {showable.map((item, position) => (
          <Image
            key={item.id}
            source={{ uri: item.url }}
            style={{ width: frameWidth, height: frameHeight }}
            contentFit="cover"
            transition={150}
            // Disk-cached, because the same demonstration is opened repeatedly and it is
            // the one part of the catalogue too heavy to re-fetch each time.
            cachePolicy="memory-disk"
            accessible
            accessibilityRole="image"
            accessibilityLabel={`${name}, demonstration ${String(position + 1)} of ${String(showable.length)}`}
          />
        ))}
      </ScrollView>

      {showable.length > 1 && (
        <View style={styles.dots}>
          {showable.map((item, position) => (
            <View
              key={item.id}
              style={[
                styles.dot,
                {
                  backgroundColor: position === index ? theme.accent : theme.border,
                },
              ]}
            />
          ))}
        </View>
      )}
    </View>
  );
}

/**
 * The small square on a picker row.
 *
 * Worth its own component because the sizing rules are different: a thumbnail must never
 * push the row taller, and a missing image must occupy exactly the same space as a
 * present one or the whole list shifts as images arrive.
 */
export function ExerciseThumbnail({
  media,
  size = 44,
}: {
  media: readonly ExerciseMedia[] | undefined;
  size?: number;
}) {
  const theme = useTheme();
  const first = (media ?? []).find(
    (item) => item.mediaType === "image" || item.mediaType === "animation",
  );

  const frame = {
    width: size,
    height: size,
    borderRadius: radius.sm,
    backgroundColor: theme.surfaceWell,
  };

  if (!first) {
    return (
      <View style={[frame, styles.centre]}>
        <Dumbbell size={Math.round(size / 2.5)} color={theme.textMuted} />
      </View>
    );
  }

  return (
    <Image
      source={{ uri: first.url }}
      style={frame}
      contentFit="cover"
      transition={100}
      cachePolicy="memory-disk"
      // Decorative here: the row's own label already names the exercise, and a second
      // announcement would make every row read twice under a screen reader.
      accessibilityElementsHidden
      importantForAccessibility="no"
    />
  );
}

/** A tappable thumbnail that opens the exercise's detail screen. */
export function ExerciseThumbnailButton({
  media,
  name,
  onPress,
  size = 44,
}: {
  media: readonly ExerciseMedia[] | undefined;
  name: string;
  onPress: () => void;
  size?: number;
}) {
  const t = useTranslate();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={t("exercises.howToDo", { name })}
      hitSlop={6}
    >
      <ExerciseThumbnail media={media} size={size} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  placeholder: { alignItems: "center", justifyContent: "center", gap: space.sm },
  centre: { alignItems: "center", justifyContent: "center" },
  dots: {
    flexDirection: "row",
    alignSelf: "center",
    gap: space.xs,
    paddingVertical: space.sm,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
});
