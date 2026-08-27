import * as AuthSession from "expo-auth-session";
import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import { Platform } from "react-native";

/**
 * Sign in with Google, on a phone.
 *
 * This exists because the web app offers Google and mobile did not — which meant anybody
 * who signed up through Google had *no password*, and therefore no way into their own
 * account from the app. That is a worse failure than a missing convenience.
 *
 * As with Apple, the token is verified server-side. Nothing here decides who the user is:
 * the id token goes to our API, which checks the signature against Google's JWKS and the
 * audience against the client ids it knows, and answers with a CoreSync session.
 *
 * **Google issues a separate OAuth client id per platform.** The one that requested the
 * token is stamped into `aud`, so an iOS build must send the iOS client id and the server
 * must be configured to accept it. Sending the web client id from a phone produces a
 * token the server correctly refuses.
 */

// Required so the browser tab closes and hands control back after the redirect.
WebBrowser.maybeCompleteAuthSession();

const DISCOVERY = {
  authorizationEndpoint: "https://accounts.google.com/o/oauth2/v2/auth",
  tokenEndpoint: "https://oauth2.googleapis.com/token",
};

export type GoogleSignInResult =
  | { kind: "success"; idToken: string; nonce: string }
  | { kind: "cancelled" }
  | { kind: "unconfigured" }
  | { kind: "failed"; message: string };

/**
 * The client id for this platform.
 *
 * Returns null rather than falling back to the web id: a token minted with the wrong
 * client id fails verification server-side with a message that says nothing useful, and
 * an unconfigured build should say so plainly instead.
 */
export function clientIdForPlatform(): string | null {
  const id =
    Platform.OS === "ios"
      ? process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID
      : Platform.OS === "android"
        ? process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID
        : process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID;

  return id && id.length > 0 ? id : null;
}

export function isGoogleSignInConfigured(): boolean {
  return clientIdForPlatform() !== null;
}

/**
 * A single-use nonce, hashed for the request and kept raw for the server.
 *
 * Identical in shape to the Apple flow and for the same reason: the provider embeds the
 * hash, and the server compares against the raw value. Sending the hash onward is a
 * nonce mismatch that reads as a server bug.
 */
export async function makeNonce(): Promise<{ raw: string; hashed: string }> {
  const bytes = await Crypto.getRandomBytesAsync(32);
  const raw = Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  const hashed = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, raw);
  return { raw, hashed };
}

/**
 * Run the Google flow and return an id token.
 *
 * Uses the implicit `id_token` response rather than an authorisation code, because the
 * code exchange needs a client *secret* — and a secret shipped in a mobile binary is not
 * a secret. The id token is all the server needs to establish identity.
 */
export async function signInWithGoogle(): Promise<GoogleSignInResult> {
  const clientId = clientIdForPlatform();
  if (!clientId) return { kind: "unconfigured" };

  const { raw, hashed } = await makeNonce();

  try {
    const request = new AuthSession.AuthRequest({
      clientId,
      scopes: ["openid", "profile", "email"],
      responseType: AuthSession.ResponseType.IdToken,
      redirectUri: AuthSession.makeRedirectUri(),
      extraParams: {
        // Google embeds the SHA-256 of this; the raw value goes to our API.
        nonce: hashed,
      },
    });

    const result = await request.promptAsync(DISCOVERY);

    if (result.type === "cancel" || result.type === "dismiss") {
      // A closed browser tab is a decision, not a fault. Showing an error would put a
      // banner in front of somebody who simply changed their mind.
      return { kind: "cancelled" };
    }
    if (result.type !== "success") {
      return { kind: "failed", message: "Google sign-in did not complete. Try again." };
    }

    const idToken = result.params.id_token;
    if (!idToken) {
      // Google returned without the one thing the server can verify.
      return { kind: "failed", message: "Google did not return a sign-in token." };
    }

    return { kind: "success", idToken, nonce: raw };
  } catch {
    return { kind: "failed", message: "Google sign-in did not complete. Try again." };
  }
}
