import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useColorScheme } from "react-native";

import { storage } from "@/lib/storage";

import { type Theme, type ThemeName, themes } from "./tokens";

export * from "./tokens";

/** What the user chose. "system" means follow the device, which is the default. */
export type ThemePreference = ThemeName | "system";

const STORAGE_KEY = "coresync.theme";

type ThemeContextValue = {
  theme: Theme;
  preference: ThemePreference;
  setPreference: (next: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme();
  const [preference, setStored] = useState<ThemePreference>("system");

  useEffect(() => {
    // Read once on mount rather than synchronously: a blocking read on the very first
    // frame is the difference between a splash that feels instant and one that stutters.
    const saved = storage.getString(STORAGE_KEY);
    if (saved === "dark" || saved === "light" || saved === "system") {
      setStored(saved);
    }
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    setStored(next);
    storage.set(STORAGE_KEY, next);
  }, []);

  const value = useMemo<ThemeContextValue>(() => {
    // Dark is the fallback when the device reports nothing. This is a gym product used
    // in badly lit rooms, and a white screen at 6am is a genuine complaint.
    const resolved: ThemeName =
      preference === "system" ? (system === "light" ? "light" : "dark") : preference;
    return { theme: themes[resolved], preference, setPreference };
  }, [preference, setPreference, system]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context.theme;
}

export function useThemePreference() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useThemePreference must be used inside ThemeProvider");
  return { preference: context.preference, setPreference: context.setPreference };
}
