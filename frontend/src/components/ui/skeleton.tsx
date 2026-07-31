import { cn } from "@/lib/utils/cn";

/**
 * A loading placeholder that matches the final layout's dimensions exactly.
 *
 * The point is zero layout shift: a skeleton that is the wrong height moves the
 * content when it resolves, which is worse than showing nothing (docs/09 §6).
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-surface-well", className)}
      // Decorative: the surrounding region announces its own loading state.
      aria-hidden
      {...props}
    />
  );
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn("h-4", index === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-lg border border-border bg-surface p-5", className)}>
      <Skeleton className="mb-4 h-3 w-24" />
      <Skeleton className="mb-2 h-12 w-32" />
      <Skeleton className="h-3 w-20" />
    </div>
  );
}
