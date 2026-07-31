"use client";

import { Check, Trophy } from "lucide-react";

import { cn } from "@/lib/utils/cn";

export type SetKind = "normal" | "warmup" | "drop" | "failure";

export type SetRowValue = {
  id: string;
  index: number;
  kind: SetKind;
  weightKg: number | null;
  reps: number | null;
  completed: boolean;
  isPr?: boolean;
};

const KIND_LABEL: Record<SetKind, string> = {
  normal: "",
  warmup: "W",
  drop: "D",
  failure: "F",
};

/**
 * The product's most-used component (docs/09 §6).
 *
 * Fixed column grid so the numbers line up down the page, `tabular-nums` so they
 * do not jitter as they change, and a 48px row that is tappable mid-set with
 * sweaty hands.
 */
export function SetRow({
  value,
  onChange,
  onToggleComplete,
}: {
  value: SetRowValue;
  onChange: (next: Partial<SetRowValue>) => void;
  onToggleComplete: () => void;
}) {
  const label = KIND_LABEL[value.kind] || value.index;

  return (
    <div
      className={cn(
        "grid h-12 grid-cols-[2.5rem_1fr_1fr_3rem] items-center gap-2 rounded-md px-2",
        value.completed ? "bg-accent/10" : "hover:bg-surface-well",
      )}
    >
      <span
        className={cn(
          "tabular flex h-7 w-7 items-center justify-center rounded-sm text-caption",
          value.kind === "warmup" && "bg-surface-well text-text-muted",
          value.kind === "drop" && "bg-chart-7/20 text-chart-7",
          value.kind === "failure" && "bg-serious/20 text-serious",
          value.kind === "normal" && "text-text-muted",
        )}
        title={value.kind === "normal" ? `Set ${value.index}` : value.kind}
      >
        {label}
      </span>

      <label className="sr-only" htmlFor={`weight-${value.id}`}>
        Weight in kilograms, set {value.index}
      </label>
      <input
        id={`weight-${value.id}`}
        type="number"
        inputMode="decimal"
        step="2.5"
        value={value.weightKg ?? ""}
        onChange={(event) =>
          onChange({ weightKg: event.target.value === "" ? null : Number(event.target.value) })
        }
        placeholder="—"
        className="tabular h-9 w-full rounded-sm bg-surface-well px-2 text-center text-numeric-table text-text placeholder:text-text-muted"
      />

      <label className="sr-only" htmlFor={`reps-${value.id}`}>
        Reps, set {value.index}
      </label>
      <input
        id={`reps-${value.id}`}
        type="number"
        inputMode="numeric"
        step="1"
        value={value.reps ?? ""}
        onChange={(event) =>
          onChange({ reps: event.target.value === "" ? null : Number(event.target.value) })
        }
        placeholder="—"
        className="tabular h-9 w-full rounded-sm bg-surface-well px-2 text-center text-numeric-table text-text placeholder:text-text-muted"
      />

      <div className="flex items-center justify-end gap-1">
        {value.isPr && (
          <Trophy className="h-4 w-4 text-accent-text" aria-label="Personal record" />
        )}
        <button
          type="button"
          onClick={onToggleComplete}
          aria-pressed={value.completed}
          aria-label={value.completed ? `Mark set ${value.index} incomplete` : `Complete set ${value.index}`}
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-sm border transition-colors",
            value.completed
              ? "border-accent bg-accent text-accent-ink"
              : "border-border text-text-muted hover:border-border-strong",
          )}
        >
          <Check className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}
