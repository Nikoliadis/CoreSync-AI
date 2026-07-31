"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Rest timer driven by an absolute end time, never a decrementing counter
 * (docs/07 §4, docs/09 §6).
 *
 * The distinction is the whole point. A counter that ticks down in state stops
 * when the tab is backgrounded, the phone sleeps or the browser throttles
 * timers — which on mobile is most of a rest period. Storing `endsAt` and
 * recomputing against the wall clock means the number is correct when the user
 * comes back, however long the page was frozen.
 *
 * `remaining` is *derived* rather than stored: the interval only advances a
 * clock reading, so there is no state to drift out of sync with `endsAt`.
 */
export function useRestTimer() {
  const [endsAt, setEndsAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const announcedRef = useRef(false);

  useEffect(() => {
    if (endsAt === null) return;

    const id = window.setInterval(() => setNow(Date.now()), 250);

    // Recompute the instant the screen lights up rather than waiting for the
    // next tick, so the number is never briefly stale on return.
    const onVisible = () => {
      if (document.visibilityState === "visible") setNow(Date.now());
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [endsAt]);

  const remaining =
    endsAt === null ? 0 : Math.max(0, Math.ceil((endsAt - Math.max(now, 0)) / 1000));

  const isRunning = endsAt !== null && remaining > 0;
  const isComplete = endsAt !== null && remaining === 0;

  // Haptics are a nicety — absent on desktop and iOS Safari — so they are never
  // the only completion signal; the UI changes regardless.
  useEffect(() => {
    if (!isComplete) {
      announcedRef.current = false;
      return;
    }
    if (announcedRef.current) return;
    announcedRef.current = true;
    if (typeof navigator !== "undefined" && "vibrate" in navigator) {
      navigator.vibrate?.([120, 60, 120]);
    }
  }, [isComplete]);

  const start = useCallback((seconds: number) => {
    const from = Date.now();
    setNow(from);
    setEndsAt(from + seconds * 1000);
  }, []);

  const add = useCallback((seconds: number) => {
    setNow(Date.now());
    setEndsAt((current) => (current ?? Date.now()) + seconds * 1000);
  }, []);

  const stop = useCallback(() => setEndsAt(null), []);

  return { remaining, isRunning, isComplete, start, add, stop };
}

export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
