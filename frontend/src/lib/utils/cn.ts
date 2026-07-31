import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * Type scale from `globals.css` (docs/09 §4). Must stay in step with it.
 *
 * tailwind-merge has to be told these are *font sizes*. Out of the box it sees any
 * `text-*` class it does not recognise and folds it into one group, so a button
 * carrying both `text-accent-ink` (a colour) and `text-body` (a size) had the colour
 * silently dropped as a duplicate — every primary button rendered white-on-lime at a
 * 1.17 contrast ratio until the accessibility gate caught it.
 */
const FONT_SIZES = [
  "overline",
  "caption",
  "body",
  "body-lg",
  "h3",
  "h2",
  "h1",
  "display",
  "hero",
] as const;

/** Semantic colours from `globals.css` §2.4. Also kept in step by hand. */
const COLORS = [
  "bg",
  "surface",
  "surface-raised",
  "surface-well",
  "border",
  "border-strong",
  "text",
  "text-secondary",
  "text-muted",
  "accent",
  "accent-hover",
  "accent-soft",
  "accent-ink",
  "accent-text",
  "focus",
  "good",
  "warning",
  "serious",
  "critical",
  "chart-1",
  "chart-2",
  "chart-3",
  "chart-4",
  "chart-5",
  "chart-6",
  "chart-7",
  "chart-8",
  "chart-grid",
] as const;

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: [...FONT_SIZES] }],
      "text-color": [{ text: [...COLORS] }],
      "bg-color": [{ bg: [...COLORS] }],
      "border-color": [{ border: [...COLORS] }],
    },
  },
});

/**
 * Merge conditional class names, letting later Tailwind utilities win.
 *
 * Without `twMerge`, a component's own `px-4` and a caller's `px-6` both land in the
 * class list and the winner is decided by stylesheet order rather than by the caller —
 * the opposite of what every consumer expects.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
