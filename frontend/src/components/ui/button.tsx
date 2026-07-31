"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef } from "react";

import { cn } from "@/lib/utils/cn";

const button = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md",
    "font-medium transition-colors duration-150 ease-[cubic-bezier(0.2,0,0,1)]",
    "disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      variant: {
        // Brand is a light colour, so text on it is near-black (docs/09 §2.1).
        primary: "bg-accent text-accent-ink hover:bg-accent-hover active:bg-accent-hover",
        secondary:
          "bg-surface-well text-text hover:bg-surface-raised border border-border",
        ghost: "text-text-secondary hover:bg-surface-well hover:text-text",
        destructive: "bg-critical text-white hover:opacity-90",
        link: "text-accent-text underline-offset-4 hover:underline",
      },
      size: {
        // 44px is the minimum touch target (docs/09 §9); `sm` is for dense
        // desktop toolbars where a pointer is guaranteed.
        sm: "h-9 px-3 text-caption",
        md: "h-11 px-4 text-body",
        lg: "h-13 px-6 text-body-lg",
        icon: "h-11 w-11",
      },
      block: { true: "w-full", false: "" },
    },
    defaultVariants: { variant: "primary", size: "md", block: false },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof button> & {
    asChild?: boolean;
    loading?: boolean;
  };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, block, asChild, loading, children, disabled, ...props },
  ref,
) {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      ref={ref}
      className={cn(button({ variant, size, block }), className)}
      disabled={disabled || loading}
      // Announced to screen readers; the visual spinner alone says nothing.
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        // The label is hidden but still laid out, with the spinner overlaid, so
        // the button keeps its exact width and a toolbar does not reflow
        // mid-submit (docs/09 §6).
        <span className="relative inline-flex items-center justify-center gap-2">
          <span className="invisible inline-flex items-center gap-2">{children}</span>
          <Loader2
            className="absolute inset-0 m-auto h-4 w-4 animate-spin"
            aria-hidden
          />
          <span className="sr-only">Working…</span>
        </span>
      ) : (
        children
      )}
    </Comp>
  );
});
