import { cn } from "@/lib/utils/cn";

export type EmptyStateProps = {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
};

/**
 * Every list gets one, written specifically for that list (docs/09 §6).
 *
 * The copy rule matters as much as the layout: an empty day is "Ready when you
 * are", never "You skipped your workout". Shame drives churn (docs/09 §1, §10).
 */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {icon && <div className="text-text-muted" aria-hidden>{icon}</div>}
      <div className="flex flex-col gap-1">
        <p className="text-h3 text-text">{title}</p>
        {description && (
          <p className="mx-auto max-w-sm text-body text-text-secondary">{description}</p>
        )}
      </div>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
