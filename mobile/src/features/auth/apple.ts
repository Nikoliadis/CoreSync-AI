import * as AppleAuthentication from "expo-apple-authentication";
import * as Crypto from "expo-crypto";
import { Platform } from "react-native";

/**
 * Sign in with Apple, native.
 *
 * The identity token produced here is **not** trusted by anything on the device. It goes
 * straight to our API, which verifies the signature against Apple's JWKS, checks the
 * issuer and the audience, and only then issues a CoreSync session. Everything Apple
 * hands us — the email, the name, the user identifier — is a claim until the server has
 * said otherwise.
 *
 * Two Apple behaviours drive the shape of this module, and both cause bugs when ignored:
 *
 * **The name arrives once.** Apple returns `fullName` only on the very first
 * authorisation for a given app, and never again — not even after the app is deleted and
 * reinstalled. If it is not captured and forwarded at that single opportunity it is gone
 * permanently, and the account is left with no display name. That is why the name is sent
 * alongside the token rather than read from a later profile call.
 *
 * **The nonce is hashed going out and raw coming back.** Apple embeds the SHA-256 of
 * whatever nonce it is given, so the server needs the *raw* value to compare against.
 * Sending the hash to Apple and the raw string to our API is the whole protocol; getting
 * it backwards produces a nonce mismatch that looks like a server bug.
 */

export type AppleSignInResult =
  | { kind: "success"; idToken: string; nonce: string; displayName: string | null }
  | { kind: "cancelled" }
  | { kind: "unavailable" }
  | { kind: "failed"; message: string };

/** Apple Sign In exists on iOS 13+ only. Never claim it elsewhere. */
export async function isAppleSignInAvailable(): Promise<boolean> {
  if (Platform.OS !== "ios") return false;
  try {
    return await AppleAuthentication.isAvailableAsync();
  } catch {
    return false;
  }
}

/**
 * A single-use random nonce, and its SHA-256.
 *
 * The nonce is what stops a token captured from one sign-in being replayed into another.
 * Generated per attempt and never reused or stored.
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
 * Join the name parts Apple returns into something displayable.
 *
 * Apple gives given and family names separately and either may be absent — a person with
 * a mononym, or someone who edited the name on the consent sheet. Returns null rather
 * than an empty or half-formed string, so the caller sends nothing instead of sending
 * whitespace as somebody's name.
 */
export function displayNameFrom(
  fullName: AppleAuthentication.AppleAuthenticationFullName | null,
): string | null {
  if (!fullName) return null;
  const parts = [fullName.givenName, fullName.familyName].filter(
    (part): part is string => typeof part === "string" && part.trim().length > 0,
  );
  const joined = parts.join(" ").trim();
  return joined.length > 0 ? joined : null;
}

/** True when the user dismissed the sheet rather than something going wrong. */
export function isCancellation(error: unknown): boolean {
  // Apple's own code for a dismissed sheet. Treating it as a failure would put an error
  // banner in front of somebody who simply changed their mind.
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "ERR_REQUEST_CANCELED"
  );
}

/**
 * Run the native sheet and return the credential.
 *
 * Never throws for a user action. A cancellation is a normal outcome and is reported as
 * one; only a genuine failure carries a message worth showing.
 */
export async function signInWithApple(): Promise<AppleSignInResult> {
  if (!(await isAppleSignInAvailable())) return { kind: "unavailable" };

  const { raw, hashed } = await makeNonce();

  try {
    const credential = await AppleAuthentication.signInAsync({
      requestedScopes: [
        AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
        AppleAuthentication.AppleAuthenticationScope.EMAIL,
      ],
      // Apple embeds the SHA-256 of this. The raw value goes to our server.
      nonce: hashed,
    });

    if (!credential.identityToken) {
      // Documented as optional in the type, and genuinely absent if the authorisation
      // was interrupted. Without it there is nothing the server can verify.
      return { kind: "failed", message: "Apple did not return a sign-in token." };
    }

    return {
      kind: "success",
      idToken: credential.identityToken,
      nonce: raw,
      // The one and only chance to capture this.
      displayName: displayNameFrom(credential.fullName),
    };
  } catch (error) {
    if (isCancellation(error)) return { kind: "cancelled" };
    return {
      kind: "failed",
      message: "Apple sign-in did not complete. Try again.",
    };
  }
}
