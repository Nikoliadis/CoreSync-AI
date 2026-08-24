// Installs a conforming `crypto.getRandomValues` on the global. Imported first and
// for its side effect only: UUIDv7 generation depends on it, and every offline write
// mints an id before anything else happens.
import "expo-crypto";

import { QueryClientProvider } from "@tanstack/react-query";
import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useRef, useState } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { createQueryClient } from "@/lib/api/query-client";
import { tokenStore } from "@/lib/api/client";
import { I18nProvider } from "@/lib/i18n";
import { storage } from "@/lib/storage";
import { openDatabase } from "@/offline/database";
import { startSyncEngine, type SyncEngineHandle } from "@/offline/sync-engine";
import { useAuth } from "@/stores/auth";
import { ThemeProvider, useTheme } from "@/theme";

// Held until the session has been restored, so a returning user never sees the login
// screen flash past on the way to their dashboard.
void SplashScreen.preventAutoHideAsync();

const PERSISTED_KEYS = ["coresync.theme", "coresync.locale"] as const;

export default function RootLayout() {
  const queryClient = useMemo(createQueryClient, []);
  const [ready, setReady] = useState(false);
  const restore = useAuth((state) => state.restore);
  const logout = useAuth((state) => state.logout);

  useEffect(() => {
    (async () => {
      // Order matters: preferences before the first paint so the theme is right, the
      // database before the sync engine so there is a queue to drain.
      await storage.hydrate(PERSISTED_KEYS);
      await openDatabase();
      await restore();
      setReady(true);
      await SplashScreen.hideAsync();
    })();
  }, [restore]);

  useEffect(() => {
    // A refresh that fails for good has to reach the UI, or the app sits on a dead
    // session showing empty screens.
    tokenStore.onExpired(() => {
      void logout();
    });
  }, [logout]);

  if (!ready) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <I18nProvider>
            <QueryClientProvider client={queryClient}>
              <ThemedStatusBar />
              <SyncEngine />
              <AuthGate />
            </QueryClientProvider>
          </I18nProvider>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

function ThemedStatusBar() {
  const theme = useTheme();
  return <StatusBar style={theme.name === "dark" ? "light" : "dark"} />;
}

/** Runs for as long as there is a session, and only while there is one. */
function SyncEngine() {
  const status = useAuth((state) => state.status);
  const handle = useRef<SyncEngineHandle | null>(null);

  useEffect(() => {
    if (status !== "authenticated") {
      handle.current?.stop();
      handle.current = null;
      return;
    }
    handle.current ??= startSyncEngine();
    return () => {
      handle.current?.stop();
      handle.current = null;
    };
  }, [status]);

  return null;
}

/**
 * Sends the user where their session says they belong.
 *
 * Done here rather than per-screen: a guard applied route by route is one somebody
 * forgets on the route they add next, and the failure is silent — the screen simply
 * works for everyone.
 */
function AuthGate() {
  const status = useAuth((state) => state.status);
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    const inAuthGroup = segments[0] === "(auth)";

    if (status === "anonymous" && !inAuthGroup) {
      router.replace("/(auth)/welcome");
    } else if (status === "authenticated" && inAuthGroup) {
      router.replace("/(tabs)");
    }
  }, [status, segments, router]);

  return (
    <Stack screenOptions={{ headerShown: false, animation: "fade" }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen
        name="workout/active"
        options={{ presentation: "fullScreenModal", animation: "slide_from_bottom" }}
      />
    </Stack>
  );
}
