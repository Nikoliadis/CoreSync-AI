import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Sign in with Google, client side.
 *
 * This exists because the web app offered Google and mobile did not — which left anyone
 * who signed up through Google with no password and therefore no way into their own
 * account from the phone.
 *
 * The rule with teeth here is the client id. Google issues a *separate* one per platform
 * and stamps whichever requested the token into `aud`. Sending the web id from a phone
 * produces a token the server refuses, with a message that says nothing about why — so
 * the platform mapping is pinned, and an unconfigured build reports that plainly instead
 * of offering a button that can only fail.
 */

const authSession = vi.hoisted(() => ({
  ResponseType: { IdToken: "id_token" },
  makeRedirectUri: vi.fn(() => "coresync://redirect"),
  AuthRequest: vi.fn(),
}));

const crypto = vi.hoisted(() => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  getRandomBytesAsync: vi.fn(),
  digestStringAsync: vi.fn(),
}));

const rn = vi.hoisted(() => ({ Platform: { OS: "ios" } }));

vi.mock("expo-auth-session", () => authSession);
vi.mock("expo-crypto", () => crypto);
vi.mock("expo-web-browser", () => ({ maybeCompleteAuthSession: vi.fn() }));
vi.mock("react-native", () => rn);

const { signInWithGoogle, clientIdForPlatform, isGoogleSignInConfigured, makeNonce } =
  await import("./google");

/** Makes the next `promptAsync` resolve with this. */
function promptResolves(value: unknown) {
  authSession.AuthRequest.mockImplementation(() => ({
    promptAsync: vi.fn().mockResolvedValue(value),
  }));
}

/** The options the AuthRequest was constructed with. */
function requestOptions(): Record<string, never> {
  return authSession.AuthRequest.mock.calls[0]?.[0] as Record<string, never>;
}

beforeEach(() => {
  vi.clearAllMocks();
  rn.Platform.OS = "ios";
  process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID = "ios.apps.googleusercontent.com";
  process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID = "android.apps.googleusercontent.com";
  process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID = "web.apps.googleusercontent.com";
  crypto.getRandomBytesAsync.mockResolvedValue(new Uint8Array([0xde, 0xad]));
  crypto.digestStringAsync.mockResolvedValue("hashed-nonce");
  promptResolves({ type: "success", params: { id_token: "google.id.token" } });
});

describe("the client id", () => {
  it("uses the iOS id on iOS", () => {
    expect(clientIdForPlatform()).toBe("ios.apps.googleusercontent.com");
  });

  it("uses the Android id on Android", () => {
    rn.Platform.OS = "android";
    expect(clientIdForPlatform()).toBe("android.apps.googleusercontent.com");
  });

  it("never falls back to the web id on a phone", () => {
    // The failure this prevents: a token minted with the web client id fails server-side
    // verification, and the error says nothing about which id was wrong.
    delete process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID;
    expect(clientIdForPlatform()).toBeNull();
  });

  it("treats an empty string as unconfigured", () => {
    process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID = "";
    expect(isGoogleSignInConfigured()).toBe(false);
  });
});

describe("the nonce", () => {
  it("hashes what Google gets and keeps the raw value", async () => {
    const { raw, hashed } = await makeNonce();

    expect(raw).toBe("dead");
    expect(hashed).toBe("hashed-nonce");
  });

  it("sends the hash to Google and the raw value onward", async () => {
    // Backwards means Google embeds a hash of a hash and the server's comparison fails
    // every time, looking like a server bug.
    const result = await signInWithGoogle();

    expect(requestOptions().extraParams).toEqual({ nonce: "hashed-nonce" });
    expect(result.kind === "success" && result.nonce).toBe("dead");
  });
});

describe("the request", () => {
  it("asks for an id token rather than a code", async () => {
    // A code exchange needs a client secret, and a secret shipped in a mobile binary is
    // not a secret. The id token is all the server needs.
    await signInWithGoogle();
    expect(requestOptions().responseType).toBe("id_token");
  });

  it("requests the scopes the server reads", async () => {
    await signInWithGoogle();
    expect(requestOptions().scopes).toEqual(["openid", "profile", "email"]);
  });
});

describe("outcomes", () => {
  it("returns the id token for the server to verify", async () => {
    const result = await signInWithGoogle();

    expect(result.kind).toBe("success");
    expect(result.kind === "success" && result.idToken).toBe("google.id.token");
  });

  it("reports a closed browser tab as a cancellation", async () => {
    // A decision, not a fault. An error banner here is shown to somebody who simply
    // changed their mind.
    promptResolves({ type: "cancel" });
    expect((await signInWithGoogle()).kind).toBe("cancelled");

    promptResolves({ type: "dismiss" });
    expect((await signInWithGoogle()).kind).toBe("cancelled");
  });

  it("fails cleanly when Google returns without a token", async () => {
    promptResolves({ type: "success", params: {} });

    const result = await signInWithGoogle();
    expect(result.kind).toBe("failed");
  });

  it("reports an error result as a failure", async () => {
    promptResolves({ type: "error", params: {} });
    expect((await signInWithGoogle()).kind).toBe("failed");
  });

  it("says unconfigured rather than failing when there is no client id", async () => {
    // Distinct from a failure: the fix is a build-time config change, not a retry.
    delete process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID;

    expect((await signInWithGoogle()).kind).toBe("unconfigured");
    expect(authSession.AuthRequest).not.toHaveBeenCalled();
  });

  it("never throws, so a screen cannot crash on a sign-in attempt", async () => {
    authSession.AuthRequest.mockImplementation(() => {
      throw new Error("boom");
    });
    await expect(signInWithGoogle()).resolves.toBeDefined();
  });
});
