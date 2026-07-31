/**
 * Shared chart theme (docs/09 §3).
 *
 * Slots are assigned in fixed order and never cycled: colour follows the entity,
 * so filtering a series out never repaints the survivors. A ninth series is
 * never a generated hue — fold into "Other" or facet instead.
 */
export const CHART_SLOTS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
  "var(--color-chart-7)",
  "var(--color-chart-8)",
] as const;

/** The product's fixed series → slot mapping, so volume is always blue. */
export const SERIES_COLOR = {
  volume: CHART_SLOTS[0],
  calories: CHART_SLOTS[1],
  protein: CHART_SLOTS[2],
  carbs: CHART_SLOTS[3],
  fat: CHART_SLOTS[4],
  weight: CHART_SLOTS[0],
} as const;

export const axisStyle = {
  stroke: "var(--color-chart-grid)",
  tick: {
    fill: "var(--color-text-muted)",
    fontSize: 12,
    // Axis ticks are tabular so digits line up vertically (docs/09 §3.2).
    style: { fontVariantNumeric: "tabular-nums" as const },
  },
  tickLine: false,
  axisLine: false,
};

export const gridStyle = {
  stroke: "var(--color-chart-grid)",
  strokeDasharray: "0",
  // Horizontal only: vertical gridlines add ink without adding meaning on a
  // time axis.
  vertical: false,
};

export const tooltipStyle = {
  contentStyle: {
    background: "var(--color-surface-raised)",
    border: "1px solid var(--color-border)",
    borderRadius: "12px",
    fontSize: "13px",
    color: "var(--color-text)",
    boxShadow: "var(--shadow-e3)",
  },
  labelStyle: { color: "var(--color-text-muted)", marginBottom: 4 },
  cursor: { stroke: "var(--color-border-strong)", strokeWidth: 1 },
};
