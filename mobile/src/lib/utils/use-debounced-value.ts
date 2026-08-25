import { useEffect, useState } from "react";

/**
 * Delays a fast-changing value so search-as-you-type is one request, not one per key.
 *
 * Uses the global `setTimeout` rather than `window.setTimeout` — React Native has no
 * `window`, and the web version of this hook would throw on the first keystroke.
 */
export function useDebouncedValue<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);

  return debounced;
}
