/**
 * Translation, structured for Greek from day one.
 *
 * English is the only populated catalogue right now, and that is the point: every
 * user-facing string goes through `t()` so adding `el.json` later is a translation job
 * rather than a refactor. A string hardcoded into a component today is a string somebody
 * has to hunt for in six months.
 *
 * Detection order, matching the web app:
 *   1. what the user explicitly chose, if anything
 *   2. the device locale
 *   3. English
 *
 * Kept deliberately small — no ICU message syntax, no plural rules engine. The moment
 * this product needs those it should adopt a real library; inventing half of one here
 * would be the worse outcome.
 */

import { getLocales } from "expo-localization";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { storage } from "@/lib/storage";

import { en } from "./en";

export type Locale = "en" | "el";
export const SUPPORTED_LOCALES: readonly Locale[] = ["en", "el"];

const STORAGE_KEY = "coresync.locale";

/** English is the shape every other catalogue must match. */
export type MessageKey = keyof typeof en;
export type Messages = Record<MessageKey, string>;

const catalogues: Record<Locale, Partial<Messages>> = {
  en,
  // Populated when the Greek translation lands. Missing keys fall through to English
  // rather than rendering a raw key at the user — a half-translated screen is usable,
  // `nutrition.diary.title` is not.
  el: {},
};

function detectLocale(): Locale {
  const stored = storage.getString(STORAGE_KEY);
  if (stored && SUPPORTED_LOCALES.includes(stored as Locale)) return stored as Locale;

  for (const locale of getLocales()) {
    const code = locale.languageCode?.toLowerCase();
    if (code && SUPPORTED_LOCALES.includes(code as Locale)) return code as Locale;
  }
  return "en";
}

export type TranslateFn = (key: MessageKey, vars?: Record<string, string | number>) => string;

type I18nContextValue = {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: TranslateFn;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setStored] = useState<Locale>("en");

  useEffect(() => {
    setStored(detectLocale());
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setStored(next);
    storage.set(STORAGE_KEY, next);
  }, []);

  const value = useMemo<I18nContextValue>(() => {
    const active = catalogues[locale];
    const t: TranslateFn = (key, vars) => {
      const template: string = active[key] ?? en[key] ?? String(key);
      if (!vars) return template;
      return Object.entries(vars).reduce(
        (out, [name, replacement]) => out.replaceAll(`{${name}}`, String(replacement)),
        template,
      );
    };
    return { locale, setLocale, t };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}

/** The common case: a component that only needs to translate. */
export function useTranslate(): TranslateFn {
  return useI18n().t;
}
