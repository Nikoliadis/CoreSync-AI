"use client";

import { Monitor, Moon, Sun } from "lucide-react";

import { useTheme, type Theme } from "@/components/providers/theme-provider";
import { cn } from "@/lib/utils/cn";

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/**
 * A three-way segmented control rather than a two-way switch.
 *
 * "System" has to be reachable: a binary toggle silently opts the user out of
 * following their OS, which is the setting most people actually want.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();

  return (
    <div
      className={cn("inline-flex rounded-md border border-border bg-surface-well p-0.5", className)}
      role="radiogroup"
      aria-label="Colour theme"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const selected = theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            onClick={() => setTheme(value)}
            className={cn(
              "flex h-9 w-9 items-center justify-center rounded-sm transition-colors",
              selected
                ? "bg-surface-raised text-text shadow-e1"
                : "text-text-muted hover:text-text",
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
          </button>
        );
      })}
    </div>
  );
}
