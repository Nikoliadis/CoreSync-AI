import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

/**
 * The rest timer.
 *
 * Deadline-based rather than tick-based: it stores *when rest ends* and derives the
 * remaining seconds from the clock. A countdown that decrements a counter every second
 * loses time whenever the screen locks, and the screen locking between sets is the
 * normal case — docs/08 §1 lists it as one of the constraints that drives the design.
 *
 * That also makes it survive backgrounding for free. The app returns, reads the clock,
 * and is correct.
 */
export type RestTimer = {
  /** Seconds left, or null when not resting. */
  remaining: number | null;
  isResting: boolean;
  start: (seconds: number) => void;
  skip: () => void;
  add: (seconds: number) => void;
};

export const DEFAULT_REST_SECONDS = 120;

export function useRestTimer(): RestTimer {
  const [endsAt, setEndsAt] = useState<number | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const fired = useRef(false);

  const recompute = useCallback((deadline: number | null) => {
    if (deadline === null) {
      setRemaining(null);
      return;
    }
    const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    setRemaining(left);

    if (left === 0 && !fired.current) {
      fired.current = true;
      // The one place a heavier haptic is warranted: the user is not looking at the
      // screen, which is the entire reason the timer exists.
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    }
  }, []);

  useEffect(() => {
    if (endsAt === null) return;
    recompute(endsAt);
    const id = setInterval(() => recompute(endsAt), 500);
    return () => clearInterval(id);
  }, [endsAt, recompute]);

  useEffect(() => {
    // Coming back from the background: re-derive rather than trusting whatever the
    // interval managed to run while suspended.
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") recompute(endsAt);
    });
    return () => subscription.remove();
  }, [endsAt, recompute]);

  const start = useCallback((seconds: number) => {
    fired.current = false;
    setEndsAt(Date.now() + seconds * 1000);
  }, []);

  const skip = useCallback(() => {
    setEndsAt(null);
    setRemaining(null);
  }, []);

  const add = useCallback((seconds: number) => {
    setEndsAt((current) => (current === null ? null : current + seconds * 1000));
  }, []);

  return { remaining, isResting: remaining !== null && remaining > 0, start, skip, add };
}

export function formatRest(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}
