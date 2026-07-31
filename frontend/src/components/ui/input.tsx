"use client";

import { forwardRef, useId } from "react";

import { cn } from "@/lib/utils/cn";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
  error?: string;
  leadingIcon?: React.ReactNode;
  trailingSlot?: React.ReactNode;
};

/**
 * Labels sit above the field, never inside it.
 *
 * Placeholder-as-label disappears the moment someone starts typing, which is
 * exactly when they most need to check what the field was (docs/09 §6).
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, label, hint, error, leadingIcon, trailingSlot, id, ...props },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={inputId} className="text-caption text-text-secondary">
          {label}
        </label>
      )}

      <div className="relative">
        {leadingIcon && (
          <span
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
            aria-hidden
          >
            {leadingIcon}
          </span>
        )}

        <input
          ref={ref}
          id={inputId}
          className={cn(
            "h-11 w-full rounded-md border bg-surface-well px-3 text-body text-text",
            "placeholder:text-text-muted",
            "transition-colors duration-150",
            "disabled:cursor-not-allowed disabled:opacity-50",
            leadingIcon && "pl-10",
            trailingSlot && "pr-11",
            error ? "border-critical" : "border-border hover:border-border-strong",
            className,
          )}
          // Colour alone never carries the error state — the message below is
          // wired up here so a screen reader announces it too (docs/09 §9).
          aria-invalid={error ? true : undefined}
          aria-describedby={cn(hint && hintId, error && errorId) || undefined}
          {...props}
        />

        {trailingSlot && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2">{trailingSlot}</span>
        )}
      </div>

      {hint && !error && (
        <p id={hintId} className="text-caption text-text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-caption text-critical" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});
