import * as SecureStore from "expo-secure-store";

/**
 * The refresh token, in the platform keystore.
 *
 * Keychain on iOS, EncryptedSharedPreferences on Android. The web app never has to do
 * this — its refresh token lives in an httpOnly cookie the browser sends on its own —
 * but a native app holds its own credential, and where it holds it is the whole
 * security story.
 *
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY` is deliberate: the token must not travel in an
 * encrypted backup to a new device, because a token restored onto someone else's phone
 * is a session on someone else's phone.
 */
const REFRESH_KEY = "coresync.refresh";

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export const secureTokens = {
  async getRefreshToken(): Promise<string | null> {
    try {
      return await SecureStore.getItemAsync(REFRESH_KEY, OPTIONS);
    } catch {
      // A keystore that refuses to open — a device with no passcode set, usually — is
      // a logged-out user, not a crash.
      return null;
    }
  },

  async setRefreshToken(token: string): Promise<void> {
    await SecureStore.setItemAsync(REFRESH_KEY, token, OPTIONS);
  },

  async clear(): Promise<void> {
    try {
      await SecureStore.deleteItemAsync(REFRESH_KEY, OPTIONS);
    } catch {
      // Already gone is the desired state.
    }
  },
};
