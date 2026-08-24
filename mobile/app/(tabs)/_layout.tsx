import { Tabs } from "expo-router";
import { Dumbbell, Home, Plus, User, UtensilsCrossed } from "lucide-react-native";
import { StyleSheet, View } from "react-native";

import { useTranslate } from "@/lib/i18n";
import { HIT_SIZE, radius, useTheme } from "@/theme";

/**
 * Five tabs, with the centre one an action rather than a destination.
 *
 * docs/08 §1: the phone is used between sets, under time pressure, one-handed. The
 * thing people open the app to do is log — so logging is the biggest, most central,
 * most thumb-reachable target on the screen, and it is not buried inside a tab.
 */
export default function TabsLayout() {
  const theme = useTheme();
  const t = useTranslate();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.accentText,
        tabBarInactiveTintColor: theme.textMuted,
        tabBarStyle: {
          backgroundColor: theme.surface,
          borderTopColor: theme.border,
          height: 88,
          paddingTop: 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
        // Every tab is at least a 44pt target, before the label is counted.
        tabBarItemStyle: { minHeight: HIT_SIZE },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t("tabs.home"),
          tabBarIcon: ({ color, size }) => <Home color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="workouts"
        options={{
          title: t("tabs.workouts"),
          tabBarIcon: ({ color, size }) => <Dumbbell color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="log"
        options={{
          title: "",
          tabBarAccessibilityLabel: t("workouts.start"),
          tabBarIcon: () => (
            <View style={[styles.fab, { backgroundColor: theme.accent }]}>
              <Plus color={theme.accentInk} size={26} strokeWidth={2.5} />
            </View>
          ),
        }}
      />
      <Tabs.Screen
        name="nutrition"
        options={{
          title: t("tabs.nutrition"),
          tabBarIcon: ({ color, size }) => <UtensilsCrossed color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: t("tabs.profile"),
          tabBarIcon: ({ color, size }) => <User color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  fab: {
    width: 56,
    height: 56,
    borderRadius: radius.full,
    alignItems: "center",
    justifyContent: "center",
    // Lifted above the bar so it reads as an action, not a fifth destination.
    marginTop: -18,
  },
});
