import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";

import { cn } from "@/lib/utils/cn";

export type StatTileProps = {
  label: string;
  value: string | number;
  unit?: string;
  /** Signed change against the comparison period. */
  delta?: number;
  deltaLabel?: string;
  /**
   * Whether a rising number is good. Weight going up is not automatically bad —
   * it depends on the user's goal — so the caller decides rather than the tile.
   */
  higherIsBetter?: boolean;
  hero?: boolean;
  className?: string;
  children?: React.ReactNode;
};

/**
 * The product's most repeated component: label, one number, one comparison
 * (docs/09 §3.3).
 *
 * Deltas pair an arrow **and** a sign with colour, never colour alone — the
 * accessibility rule and the "not everything needs a chart" rule in one.
 */
export function StatTile({
  label,
  value,
  unit,
  delta,
  deltaLabel,
  higherIsBetter = true,
  hero = false,
  className,
  children,
}: StatTileProps) {
  const hasDelta = delta !== undefined && Number.isFinite(delta);
  const isFlat = hasDelta && Math.abs(delta) < 0.005;
  const isUp = hasDelta && delta > 0;
  const isGood = isFlat ? null : isUp === higherIsBetter;

  const DeltaIcon = isFlat ? ArrowRight : isUp ? ArrowUp : ArrowDown;

  return (
    <div className={cn("rounded-lg border border-border bg-surface p-5", className)}>
      <p className="text-overline uppercase text-text-muted">{label}</p>

      <div className="mt-2 flex items-baseline gap-1.5">
        <span
          className={cn(
            "tabular text-text",
            hero ? "text-hero" : "text-h1",
          )}
        >
          {value}
        </span>
        {unit && <span className="text-caption text-text-muted">{unit}</span>}
      </div>

      {hasDelta && (
        <p
          className={cn(
            "mt-2 flex items-center gap-1 text-caption",
            isGood === null ? "text-text-muted" : isGood ? "text-good" : "text-serious",
          )}
        >
          <DeltaIcon className="h-3.5 w-3.5" aria-hidden />
          <span className="tabular">
            {delta > 0 ? "+" : ""}
            {delta}
          </span>
          {deltaLabel && <span className="text-text-muted">{deltaLabel}</span>}
        </p>
      )}

      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}
