import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { AppProviders } from "@/components/providers/app-providers";
import { themeScript } from "@/components/providers/theme-provider";

import "./globals.css";

// Self-hosted at build time by next/font, so there is no third-party request on
// the critical path and no shift from a late font swap (docs/09 §4).
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

// Only used for code blocks in the coach's answers.
const jetbrains = JetBrains_Mono({
  variable: "--font-mono-code",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "CoreSync — Train with intent",
    template: "%s · CoreSync",
  },
  description:
    "Track workouts, watch your strength trend, and get coaching grounded in your own numbers.",
};

export const viewport: Viewport = {
  // Dark is the default theme, so browser chrome matches before first paint.
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0b" },
    { media: "(prefers-color-scheme: light)", color: "#f4f4f2" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // Deliberately no `maximumScale`: blocking zoom fails WCAG and hurts exactly
  // the users who need it most (docs/09 §9).
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrains.variable} h-full antialiased`}
      // The theme script mutates <html> before React hydrates; without this the
      // class it adds is reported as a hydration mismatch.
      suppressHydrationWarning
    >
      <head>
        {/* Blocking and inline on purpose — any later approach means a
            light-mode user sees a flash of near-black first. */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
