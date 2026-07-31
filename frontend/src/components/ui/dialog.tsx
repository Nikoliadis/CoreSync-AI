"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { forwardRef } from "react";

import { cn } from "@/lib/utils/cn";

/**
 * Dialog and bottom sheet, built on Radix.
 *
 * Focus trapping, restore-on-close, `Esc`, scroll locking and `aria-modal` come
 * from the primitive rather than from us remembering to implement them
 * (docs/09 §6).
 */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(function DialogTitle({ className, ...props }, ref) {
  return <DialogPrimitive.Title ref={ref} className={cn("text-h2 text-text", className)} {...props} />;
});

export const DialogDescription = forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(function DialogDescription({ className, ...props }, ref) {
  return (
    <DialogPrimitive.Description
      ref={ref}
      className={cn("text-body text-text-secondary", className)}
      {...props}
    />
  );
});

function Overlay({ className, ...props }: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      className={cn("cs-overlay fixed inset-0 z-50 bg-black/60 backdrop-blur-sm", className)}
      {...props}
    />
  );
}

export type DialogContentProps = React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
  /** `sheet` slides from the bottom — the thumb-first pattern on mobile (docs/09 §1). */
  variant?: "dialog" | "sheet";
  showClose?: boolean;
};

export const DialogContent = forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(function DialogContent({ className, children, variant = "dialog", showClose = true, ...props }, ref) {
  return (
    <DialogPrimitive.Portal>
      <Overlay />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          "fixed z-50 border border-border bg-surface-raised shadow-e3",
          variant === "dialog"
            ? [
                "cs-dialog left-1/2 top-1/2 w-[calc(100vw-2rem)] max-w-lg",
                "-translate-x-1/2 -translate-y-1/2 rounded-xl p-6",
              ]
            : [
                "cs-sheet inset-x-0 bottom-0 max-h-[90vh] overflow-y-auto rounded-t-xl p-6",
                "sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[calc(100vw-2rem)] sm:max-w-lg",
                "sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl",
              ],
          className,
        )}
        {...props}
      >
        {children}
        {showClose && (
          <DialogPrimitive.Close
            // 44px hit area even though the glyph is 16px (docs/09 §9).
            className="absolute right-4 top-4 flex h-11 w-11 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-well hover:text-text"
            aria-label="Close"
          >
            <X className="h-4 w-4" aria-hidden />
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 flex flex-col gap-1.5 pr-12", className)} {...props} />;
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    />
  );
}
