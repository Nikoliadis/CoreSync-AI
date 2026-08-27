import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Sign in with Apple, client side.
 *
 * Two Apple behaviours drive everything here and both fail silently when got wrong.
 *
 * The **nonce is hashed going out and raw coming back**: Apple embeds SHA-256 of what it
 * is given, so the server needs the raw value to compare. Send the hash to our API and
 * every sign-in fails a nonce check that looks like a server bug.
 *
 * The **name arrives exactly once** — on the first authorisation for the app, ever, and
 * never again even after a reinstall. Failing to forward it there loses it permanently
 * and leaves the account with no display name.
 */

const apple = vi.hoisted(() => ({
  AppleAuthenticationScope: { FULL_NAME: 0, EMAIL: 1 },
  AppleAuthenticationButtonType: { SIGN_IN: 0 },
  AppleAuthenticationButtonStyle: { WHITE: 0, BLACK: 2 },
  isAvailableAsync: vi.fn(),
  signInAsync: vi.fn(),
}));

const crypto = vi.hoisted(() => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  getRandomBytesAsync: vi.fn(),
  digestStringAsync: vi.fn(),
}));

const rn = vi.hoisted(() => ({ Platform: { OS: "ios" } }));

vi.mock("expo-apple-authentication", () => apple);
vi.mock("expo-crypto", () => crypto);
vi.mock("react-native", () => rn);

const {
  signInWithApple,
  makeNonce,
  displayNameFrom,
  isCancellation,
  isAppleSignInAvailable,
} = await import("./apple");

function cancellation() {
  return Object.assign(new Error("cancelled"), { code: "ERR_REQUEST_CANCELED" });
}

beforeEach(() => {
  vi.clearAllMocks();
  rn.Platform.OS = "ios";
  apple.isAvailableAsync.mockResolvedValue(true);
  crypto.getRandomBytesAsync.mockResolvedValue(new Uint8Array([0xde, 0xad, 0xbe, 0xef]));
  crypto.digestStringAsync.mockResolvedValue("hashed-nonce");
  apple.signInAsync.mockResolvedValue({
    identityToken: "apple.identity.token",
    fullName: { givenName: "Nikos", familyName: "Papadopoulos" },
    email: "nikos@example.com",
  });
});

describe("availability", () => {
  it("is available on iOS when the OS says so", async () => {
    expect(await isAppleSignInAvailable()).toBe(true);
  });

  it("is never available off iOS", async () => {
    // A disabled Apple button on Android is a promise the platform cannot keep.
    rn.Platform.OS = "android";
    expect(await isAppleSignInAvailable()).toBe(false);
    expect(apple.isAvailableAsync).not.toHaveBeenCalled();
  });

  it("is unavailable on an iOS version without the capability", async () => {
    apple.isAvailableAsync.mockResolvedValue(false);
    expect(await isAppleSignInAvailable()).toBe(false);
  });

  it("treats a throwing availability check as unavailable", async () => {
    apple.isAvailableAsync.mockRejectedValue(new Error("no module"));
    expect(await isAppleSignInAvailable()).toBe(false);
  });
});

describe("the nonce", () => {
  it("hashes what Apple gets and keeps the raw value", async () => {
    const { raw, hashed } = await makeNonce();

    expect(raw).toBe("deadbeef");
    expect(hashed).toBe("hashed-nonce");
    expect(crypto.digestStringAsync).toHaveBeenCalledWith("SHA-256", "deadbeef");
  });

  it("sends the hash to Apple and the raw value onward", async () => {
    // Backwards here means Apple embeds the hash of a hash, and the server's comparison
    // fails every time with no indication of why.
    const result = await signInWithApple();

    expect(apple.signInAsync.mock.calls[0]?.[0].nonce).toBe("hashed-nonce");
    expect(result.kind === "success" && result.nonce).toBe("deadbeef");
  });

  it("is different on every attempt", async () => {
    crypto.getRandomBytesAsync
      .mockResolvedValueOnce(new Uint8Array([1, 2]))
      .mockResolvedValueOnce(new Uint8Array([3, 4]));

    const first = await makeNonce();
    const second = await makeNonce();
    expect(first.raw).not.toBe(second.raw);
  });
});

describe("the name Apple returns once", () => {
  it("joins the parts", () => {
    expect(displayNameFrom({ givenName: "Nikos", familyName: "Papadopoulos" } as never)).toBe(
      "Nikos Papadopoulos",
    );
  });

  it("copes with only one part, which a mononym produces", () => {
    expect(displayNameFrom({ givenName: "Nikos", familyName: null } as never)).toBe("Nikos");
  });

  it("is null rather than whitespace when Apple sends nothing usable", () => {
    // Sending " " would persist whitespace as somebody's display name.
    expect(displayNameFrom({ givenName: null, familyName: null } as never)).toBeNull();
    expect(displayNameFrom({ givenName: "  ", familyName: "" } as never)).toBeNull();
    expect(displayNameFrom(null)).toBeNull();
  });

  it("is forwarded on the first authorisation", async () => {
    const result = await signInWithApple();
    expect(result.kind === "success" && result.displayName).toBe("Nikos Papadopoulos");
  });

  it("is null on every later authorisation, as Apple sends none", async () => {
    // The real second-sign-in payload. The account must already have the name by now.
    apple.signInAsync.mockResolvedValue({
      identityToken: "apple.identity.token",
      fullName: null,
    });

    const result = await signInWithApple();
    expect(result.kind === "success" && result.displayName).toBeNull();
  });
});

describe("outcomes", () => {
  it("returns the identity token for the server to verify", async () => {
    const result = await signInWithApple();

    expect(result.kind).toBe("success");
    expect(result.kind === "success" && result.idToken).toBe("apple.identity.token");
  });

  it("reports a dismissed sheet as a cancellation, not a failure", async () => {
    // Showing an error banner to somebody who changed their mind is worse than showing
    // nothing at all.
    apple.signInAsync.mockRejectedValue(cancellation());

    expect((await signInWithApple()).kind).toBe("cancelled");
  });

  it("recognises Apple's cancellation code", () => {
    expect(isCancellation(cancellation())).toBe(true);
    expect(isCancellation(new Error("something else"))).toBe(false);
    expect(isCancellation(null)).toBe(false);
  });

  it("fails cleanly when Apple returns no identity token", async () => {
    // Documented as optional, and genuinely absent when the authorisation is
    // interrupted. There is nothing for the server to verify.
    apple.signInAsync.mockResolvedValue({ identityToken: null, fullName: null });

    const result = await signInWithApple();
    expect(result.kind).toBe("failed");
  });

  it("reports a genuine error as a failure", async () => {
    apple.signInAsync.mockRejectedValue(new Error("ERR_INVALID_RESPONSE"));

    const result = await signInWithApple();
    expect(result.kind).toBe("failed");
    expect(result.kind === "failed" && result.message).toBeTruthy();
  });

  it("never throws, so a screen cannot crash on a sign-in attempt", async () => {
    apple.signInAsync.mockRejectedValue(new Error("anything"));
    await expect(signInWithApple()).resolves.toBeDefined();
  });

  it("does not run the sheet where Apple sign-in does not exist", async () => {
    rn.Platform.OS = "android";

    expect((await signInWithApple()).kind).toBe("unavailable");
    expect(apple.signInAsync).not.toHaveBeenCalled();
  });

  it("asks for the name and email scopes", async () => {
    await signInWithApple();
    expect(apple.signInAsync.mock.calls[0]?.[0].requestedScopes).toEqual([0, 1]);
  });
});
