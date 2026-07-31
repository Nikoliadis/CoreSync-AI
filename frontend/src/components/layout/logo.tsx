import Link from "next/link";

import { cn } from "@/lib/utils/cn";

/**
 * The mark is two offset bars — a barbell read abstractly — in the accent, so
 * the brand colour appears exactly once in the chrome (docs/09 §1: one accent).
 */
export function Logo({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link
      href="/dashboard"
      className={cn("flex items-center gap-2.5 rounded-md", className)}
      aria-label="CoreSync home"
    >
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent"
        aria-hidden
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
          <path
            d="M5 9v6M9 6v12M15 6v12M19 9v6"
            stroke="var(--color-accent-ink)"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
        </svg>
      </span>
      {!compact && (
        <span className="text-h3 font-semibold tracking-tight text-text">CoreSync</span>
      )}
    </Link>
  );
}
