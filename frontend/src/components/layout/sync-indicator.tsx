"use client";

import { CloudOff, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import {
  getSyncStatus,
  startSyncEngine,
  subscribeToSync,
  type SyncStatus,
} from "@/lib/offline/sync-engine";
import { cn } from "@/lib/utils/cn";

/**
 * Shows the write-ahead log's state, and only when there is something to say.
 *
 * A permanent "synced" badge is noise: the normal case is that everything is saved,
 * and a persistent indicator trains people to ignore it. This appears when work is
 * queued and disappears when it drains — so when it *is* visible it means something.
 */
export function SyncIndicator({ className }: { className?: string }) {
  const [status, setStatus] = useState<SyncStatus>(getSyncStatus);

  useEffect(() => {
    const stopEngine = startSyncEngine();
    const unsubscribe = subscribeToSync(setStatus);
    return () => {
      unsubscribe();
      stopEngine();
    };
  }, []);

  if (status.pending === 0) return null;

  const offline = Boolean(status.lastError) && !status.flushing;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-caption",
        offline ? "bg-warning/15 text-warning" : "bg-surface-well text-text-secondary",
        className,
      )}
      // Announced politely: a lifter mid-set should not be interrupted, but a screen
      // reader user still needs to know their sets are queued rather than saved.
      role="status"
      aria-live="polite"
    >
      {offline ? (
        <CloudOff className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden />
      )}
      <span className="tabular">
        {status.pending} {status.pending === 1 ? "change" : "changes"}{" "}
        {offline ? "saved offline" : "syncing"}
      </span>
    </span>
  );
}
