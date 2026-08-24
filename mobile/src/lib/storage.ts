import AsyncStorage from "@react-native-async-storage/async-storage";

/**
 * Small, non-sensitive key-value state: theme choice, last opened tab, onboarding seen.
 *
 * Deliberately *not* where tokens go — see `lib/auth/secure-tokens`. The synchronous
 * cache in front of AsyncStorage exists because the theme has to be known on the first
 * frame, and an await there is a visible flash of the wrong colour scheme.
 */
const cache = new Map<string, string>();

export const storage = {
  getString(key: string): string | undefined {
    return cache.get(key);
  },

  set(key: string, value: string): void {
    cache.set(key, value);
    void AsyncStorage.setItem(key, value);
  },

  remove(key: string): void {
    cache.delete(key);
    void AsyncStorage.removeItem(key);
  },

  /** Warm the cache before the first render. Called once, from the root layout. */
  async hydrate(keys: readonly string[]): Promise<void> {
    const entries = await AsyncStorage.multiGet([...keys]);
    for (const [key, value] of entries) {
      if (value !== null) cache.set(key, value);
    }
  },
};
