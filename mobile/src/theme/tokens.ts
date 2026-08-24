/**
 * The design system, in the one place both themes read from.
 *
 * These values are the same ones `frontend/app/globals.css` defines as CSS custom
 * properties. They are duplicated here rather than imported because React Native has no
 * CSS layer to read them from — but they are duplicated *deliberately and completely*,
 * so a colour that changes on web is a one-line change here rather than a hunt through
 * components.
 *
 * The accent is the product's identity: a single high-energy lime against near-black.
 * It is used for one thing per screen — the action the user came to take — and never
 * for decoration, or it stops meaning anything.
 */

export const palette = {
  brand400: "#d8ff6e",
  brand500: "#c8ff3d",
  brand600: "#b2e82a",
  brandInk: "#0f0f11",
} as const;

export type ThemeName = "dark" | "light";

export type Theme = {
  name: ThemeName;
  bg: string;
  surface: string;
  surfaceRaised: string;
  surfaceWell: string;
  border: string;
  borderStrong: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  accent: string;
  /** Accent used as *text*. The raw brand lime fails contrast on light backgrounds. */
  accentText: string;
  accentInk: string;
  good: string;
  warning: string;
  serious: string;
  critical: string;
  chart: readonly string[];
  chartGrid: string;
};

export const darkTheme: Theme = {
  name: "dark",
  bg: "#0a0a0b",
  surface: "#0f0f11",
  surfaceRaised: "#17171a",
  surfaceWell: "#1f1f23",
  border: "rgba(255, 255, 255, 0.08)",
  borderStrong: "rgba(255, 255, 255, 0.18)",
  text: "#ffffff",
  textSecondary: "#c3c2b7",
  textMuted: "#898781",
  accent: palette.brand500,
  accentText: "#c8ff3d",
  accentInk: palette.brandInk,
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  chart: [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
  ],
  chartGrid: "rgba(255, 255, 255, 0.07)",
};

export const lightTheme: Theme = {
  name: "light",
  bg: "#f4f4f2",
  surface: "#fafafa",
  surfaceRaised: "#ffffff",
  surfaceWell: "#f0f0ee",
  border: "rgba(11, 11, 11, 0.1)",
  borderStrong: "rgba(11, 11, 11, 0.24)",
  text: "#0b0b0b",
  textSecondary: "#52514e",
  textMuted: "#6b6a66",
  accent: palette.brand500,
  // Not the brand lime: at 1.07:1 on a light background it is unreadable. This is the
  // darkened variant the web app uses for the same reason.
  accentText: "#4f660d",
  accentInk: palette.brandInk,
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  chart: [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
  ],
  chartGrid: "rgba(11, 11, 11, 0.09)",
};

export const themes: Record<ThemeName, Theme> = {
  dark: darkTheme,
  light: lightTheme,
};

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  full: 9999,
} as const;

/** A 4px base. Every gap in the app is one of these, so rhythm stays consistent. */
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const type = {
  display: { fontSize: 40, lineHeight: 44, fontWeight: "700" },
  h1: { fontSize: 28, lineHeight: 34, fontWeight: "700" },
  h2: { fontSize: 22, lineHeight: 28, fontWeight: "600" },
  h3: { fontSize: 17, lineHeight: 24, fontWeight: "600" },
  body: { fontSize: 16, lineHeight: 24, fontWeight: "400" },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: "400" },
  overline: { fontSize: 11, lineHeight: 16, fontWeight: "600", letterSpacing: 0.8 },
} as const;

/**
 * The minimum tappable size, in points.
 *
 * 44 is Apple's floor and the WCAG target size. It is also the number that matters most
 * in this product: docs/08 opens by pointing out that hands in a gym are chalked,
 * sweaty and shaking. A control smaller than this is one that gets mis-tapped between
 * sets, and a mis-tap under time pressure is how people stop logging.
 */
export const HIT_SIZE = 44;

export const duration = {
  instant: 100,
  fast: 180,
  base: 260,
  slow: 420,
} as const;
