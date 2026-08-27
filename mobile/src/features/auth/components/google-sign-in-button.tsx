import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { Button } from "@/components/ui/button";
import { isGoogleSignInConfigured, signInWithGoogle } from "@/features/auth/google";
import { ApiError } from "@/lib/api/client";
import { useTranslate } from "@/lib/i18n";
import { useAuth } from "@/stores/auth";
import { space } from "@/theme";

/**
 * Google's official "G" mark.
 *
 * Inlined as SVG rather than a bitmap so it stays sharp at any density and adds nothing
 * to the bundle. The four brand colours are fixed by Google's identity guidelines and
 * must not be themed — recolouring the mark to match the app is exactly what the
 * guidelines forbid.
 */
function GoogleMark({ size = 18 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48">
      <Path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <Path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <Path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24s.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <Path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </Svg>
  );
}

/**
 * Sign in with Google.
 *
 * Renders nothing when no client id is configured for this platform. A button that can
 * only ever fail is worse than no button — and Google needs a *separate* client id per
 * platform, so "configured on web" does not mean configured here.
 */
export function GoogleSignInButton({ onError }: { onError?: (message: string) => void }) {
  const t = useTranslate();
  const router = useRouter();
  const signInWithProvider = useAuth((state) => state.signInWithProvider);
  const [busy, setBusy] = useState(false);

  if (!isGoogleSignInConfigured()) return null;

  const onPress = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await signInWithGoogle();

      if (result.kind === "cancelled" || result.kind === "unconfigured") return;
      if (result.kind === "failed") {
        onError?.(result.message);
        return;
      }

      // Verified server-side against Google's JWKS before any session exists.
      await signInWithProvider({
        provider: "google",
        idToken: result.idToken,
        nonce: result.nonce,
      });
      router.replace("/(tabs)");
    } catch (error) {
      if (error instanceof ApiError) {
        onError?.(error.isOffline ? t("google.needsConnection") : error.message);
      } else {
        onError?.(t("google.signInFailed"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.wrapper}>
      <Button
        label={busy ? t("apple.signingIn") : t("google.signIn")}
        variant="secondary"
        icon={<GoogleMark />}
        disabled={busy}
        onPress={() => void onPress()}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { gap: space.xs },
});
