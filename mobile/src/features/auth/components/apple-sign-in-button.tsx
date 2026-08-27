import * as AppleAuthentication from "expo-apple-authentication";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";

import { Text } from "@/components/ui/text";
import { signInWithApple } from "@/features/auth/apple";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/stores/auth";
import { radius, space, useTheme } from "@/theme";

/**
 * Apple's own button, not an imitation.
 *
 * `AppleAuthenticationButton` is a native view rendered by the system, which is what
 * Apple's Human Interface Guidelines require: the mark, the corner radius, the label
 * wording and the localisation are theirs, and review rejects a hand-built lookalike.
 * That is also why it is not styled through the app's `Button` — the only things we get
 * to choose are the type, the colour scheme and the height.
 *
 * Renders nothing at all off iOS, and nothing on an iOS version without the capability.
 * A disabled Apple button on Android would be a promise the platform cannot keep.
 */
export function AppleSignInButton({ onError }: { onError?: (message: string) => void }) {
  const router = useRouter();
  const theme = useTheme();
  const signInWithProvider = useAuth((state) => state.signInWithProvider);

  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void AppleAuthentication.isAvailableAsync()
      .then((value) => {
        if (!cancelled) setAvailable(value);
      })
      .catch(() => {
        // Not available is the answer on every non-iOS platform, where the module's
        // check throws rather than resolving false.
        if (!cancelled) setAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!available) return null;

  const onPress = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await signInWithApple();

      if (result.kind === "cancelled") return; // Not an error. Say nothing.
      if (result.kind === "unavailable") return;
      if (result.kind === "failed") {
        onError?.(result.message);
        return;
      }

      // The token is verified server-side against Apple's JWKS. Nothing here decides
      // who the user is; the API does, and answers with a CoreSync session.
      await signInWithProvider({
        provider: "apple",
        idToken: result.idToken,
        nonce: result.nonce,
        displayName: result.displayName,
      });
      router.replace("/(tabs)");
    } catch (error) {
      if (error instanceof ApiError) {
        onError?.(
          error.isOffline
            ? "No connection. Apple sign-in needs one."
            : // The server's message covers the cases worth distinguishing: an account
              // that exists with a password, a refused link, an unverifiable token.
              error.message,
        );
      } else {
        onError?.("Apple sign-in did not complete. Try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.wrapper}>
      <AppleAuthentication.AppleAuthenticationButton
        buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
        // Follows the app's theme so the button does not sit on the page as a white
        // slab in dark mode, which is the one styling choice Apple does allow.
        buttonStyle={
          theme.name === "dark"
            ? AppleAuthentication.AppleAuthenticationButtonStyle.WHITE
            : AppleAuthentication.AppleAuthenticationButtonStyle.BLACK
        }
        cornerRadius={radius.md}
        style={styles.button}
        onPress={() => void onPress()}
      />
      {busy && (
        <Text variant="caption" tone="muted" style={styles.busy}>
          Signing in…
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: space.xs },
  // Height must be set explicitly: the native view has no intrinsic size in RN's layout.
  button: { height: 48, width: "100%" },
  busy: { textAlign: "center" },
});
