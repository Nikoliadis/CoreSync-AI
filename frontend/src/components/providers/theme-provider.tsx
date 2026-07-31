"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "dark" | "light" | "system";

const STORAGE_KEY = "coresync-theme";

type ThemeContextValue = {
  /** What the user chose, including "system". */
  theme: Theme;
  /** What is actually painted right now — never "system". */
  resolved: "dark" | "light";
  setTheme: (theme: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Applies the theme by toggling a single `light` class on <html>.
 *
 * Dark is the default and needs no class, which means the server-rendered HTML
 * is already correct for the common case and only light-mode users pay for a
 * class swap (docs/09 §1).
 */
function applyTheme(resolved: "dark" | "light") {
  document.documentElement.classList.toggle("light", resolved === "light");
}

function systemPreference(): "dark" | "light" {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Initialised from the DOM rather than a constant: the blocking script in
  // <head> has already resolved and applied the theme by the time React mounts,
  // so reading it back avoids a second, conflicting decision.
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === "undefined") return "system";
    return (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "system";
  });
  const [resolved, setResolved] = useState<"dark" | "light">(() => {
    if (typeof window === "undefined") return "dark";
    return document.documentElement.classList.contains("light") ? "light" : "dark";
  });

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    localStorage.setItem(STORAGE_KEY, next);
    const effective = next === "system" ? systemPreference() : next;
    setResolved(effective);
    applyTheme(effective);
  }, []);

  // Follow the OS only while the user is on "system" — an explicit choice must
  // survive the OS flipping at sunset.
  useEffect(() => {
    if (theme !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      const effective = systemPreference();
      setResolved(effective);
      applyTheme(effective);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, resolved, setTheme }}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside <ThemeProvider>");
  return context;
}

/**
 * Runs before first paint to prevent a flash of the wrong theme.
 *
 * This has to be a blocking inline script: any React-driven approach resolves
 * after hydration, by which point a light-mode user has already been shown a
 * near-black screen. Wrapped in try/catch because localStorage throws outright
 * in some privacy modes, and a theme preference is never worth a blank page.
 */
export const themeScript = `
(function(){try{
  var stored = localStorage.getItem('${STORAGE_KEY}');
  var isLight = stored === 'light' || (stored !== 'dark' && window.matchMedia('(prefers-color-scheme: light)').matches);
  if (isLight) document.documentElement.classList.add('light');
}catch(e){}})();
`;
