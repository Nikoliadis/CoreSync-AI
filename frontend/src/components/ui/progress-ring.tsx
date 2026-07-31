"use client";

import { cn } from "@/lib/utils/cn";

export type ProgressRingProps = {
  value: number;
  max: number;
  label: string;
  unit?: string;
  size?: number;
  strokeWidth?: number;
  /** A chart slot token, e.g. `var(--color-chart-3)`. Defaults to the accent. */
  color?: string;
  className?: string;
};

/**
 * A ring is used only where there is a real denominator — calories against a
 * target, water against a goal. No decorative rings (docs/09 §3.3).
 */
export function ProgressRing({
  value,
  max,
  label,
  unit,
  size = 120,
  strokeWidth = 10,
  color = "var(--color-accent)",
  className,
}: ProgressRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const safeMax = max > 0 ? max : 1;
  // Clamped so an overshoot draws a full ring rather than winding round twice.
  const ratio = Math.min(Math.max(value / safeMax, 0), 1);
  const offset = circumference * (1 - ratio);
  const percent = Math.round(ratio * 100);
  const isOver = value > max;

  return (
    <div
      className={cn("relative inline-flex items-center justify-center", className)}
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={`${label}: ${value}${unit ? ` ${unit}` : ""} of ${max}${unit ? ` ${unit}` : ""} (${percent}%)`}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-surface-well"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          stroke={color}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-[stroke-dashoffset] duration-[420ms] ease-[cubic-bezier(0.2,0,0,1)]"
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="tabular text-h3 text-text">{Math.round(value)}</span>
        {unit && <span className="text-overline uppercase text-text-muted">{unit}</span>}
        {/* Over-target is stated in words, not just by colour (docs/09 §9). */}
        {isOver && <span className="text-caption text-warning">over</span>}
      </div>
    </div>
  );
}
