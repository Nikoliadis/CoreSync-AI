import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils/cn";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-overline uppercase",
  {
    variants: {
      tone: {
        neutral: "bg-surface-well text-text-secondary",
        accent: "bg-accent text-accent-ink",
        good: "bg-good/15 text-good",
        warning: "bg-warning/15 text-warning",
        serious: "bg-serious/15 text-serious",
        critical: "bg-critical/15 text-critical",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badge> & {
    /**
     * Status colour is never the only signal — pair it with an icon or make the
     * label itself carry the meaning (docs/09 §2.3, §9).
     */
    icon?: React.ReactNode;
  };

export function Badge({ className, tone, icon, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badge({ tone }), className)} {...props}>
      {icon}
      {children}
    </span>
  );
}
