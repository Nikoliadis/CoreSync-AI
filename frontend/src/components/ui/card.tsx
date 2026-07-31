import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef } from "react";

import { cn } from "@/lib/utils/cn";

const card = cva("rounded-lg border border-border bg-surface", {
  variants: {
    variant: {
      default: "",
      // Hover lift is the affordance that says "this navigates" (docs/09 §7).
      interactive:
        "transition-[transform,background-color] duration-[180ms] ease-[cubic-bezier(0.2,0,0,1)] hover:-translate-y-0.5 hover:bg-surface-raised cursor-pointer",
      raised: "bg-surface-raised shadow-e2",
    },
    padding: { none: "", sm: "p-4", md: "p-5", lg: "p-6" },
  },
  defaultVariants: { variant: "default", padding: "md" },
});

export type CardProps = React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof card>;

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, variant, padding, ...props },
  ref,
) {
  return <div ref={ref} className={cn(card({ variant, padding }), className)} {...props} />;
});

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 flex items-start justify-between gap-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-h3 text-text", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-caption text-text-muted", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-4 flex items-center gap-3", className)} {...props} />;
}
