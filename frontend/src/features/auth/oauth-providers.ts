/**
 * Google and Apple sign-in, browser side.
 *
 * Both use the **ID-token** flow rather than an authorisation-code exchange: the provider
 * hands the browser a signed assertion, and the backend verifies it against the
 * provider's JWKS. That is why nothing here needs a client *secret* — there is none in
 * the bundle to leak, and the browser is never trusted with anything beyond a token the
 * server independently validates.
 *
 * The client IDs below are public by design. A Google client ID is visible in every
 * page that uses it; what protects the account is the authorised-origins list configured
 * on Google's side, not secrecy.
 *
 * Both scripts are loaded on demand rather than in the document head. They are third
 * party, they are only needed on two routes, and a landing page should not pay for a
 * script most visitors never trigger.
 */

export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
export const APPLE_SERVICE_ID = process.env.NEXT_PUBLIC_APPLE_SERVICE_ID ?? "";

const GOOGLE_SRC = "https://accounts.google.com/gsi/client";
const APPLE_SRC =
  "https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js";

export type OAuthProvider = "google" | "apple";

export type OAuthResult = {
  idToken: string;
  nonce?: string;
  /** Apple returns a name on first authorisation only. */
  displayName?: string;
};

export function isConfigured(provider: OAuthProvider): boolean {
  return provider === "google" ? Boolean(GOOGLE_CLIENT_ID) : Boolean(APPLE_SERVICE_ID);
}

const loaded = new Map<string, Promise<void>>();

function loadScript(src: string): Promise<void> {
  // Cached by URL: two buttons on one page must not inject the same SDK twice, and a
  // second injection of the Google script silently breaks the first one's callbacks.
  const existing = loaded.get(src);
  if (existing) return existing;

  const promise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Let a later attempt retry rather than caching the failure forever — a blocked
      // script is often a transient extension or network condition.
      loaded.delete(src);
      reject(new Error(`Could not load ${src}`));
    };
    document.head.appendChild(script);
  });

  loaded.set(src, promise);
  return promise;
}

/**
 * A random nonce, bound to this one attempt.
 *
 * The provider embeds it in the ID token and the backend checks it matches, which is
 * what stops a token captured elsewhere being replayed here.
 */
function makeNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// --------------------------------------------------------------------- google
type GoogleCredentialResponse = { credential?: string };

type GoogleAccounts = {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (response: GoogleCredentialResponse) => void;
        nonce?: string;
        use_fedcm_for_prompt?: boolean;
      }) => void;
      renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
};

declare global {
  interface Window {
    google?: GoogleAccounts;
    AppleID?: {
      auth: {
        init: (config: {
          clientId: string;
          scope: string;
          redirectURI: string;
          usePopup: boolean;
          nonce?: string;
        }) => void;
        signIn: () => Promise<{
          authorization: { id_token: string };
          user?: { name?: { firstName?: string; lastName?: string } };
        }>;
      };
    };
  }
}

/**
 * Renders Google's button into `parent` and resolves when the user signs in.
 *
 * `renderButton` is the only supported way to obtain an ID token from a user gesture in
 * the browser — One Tap is the alternative and it can be permanently dismissed. So the
 * real button is always rendered; a caller wanting its own styling hides this container
 * and forwards clicks to it via `clickGoogleButton`.
 *
 * That proxy is the honest cost of a custom mark: it reaches into Google's rendered DOM,
 * so a change on their side could break it. `clickGoogleButton` reports failure rather
 * than doing nothing, which is what makes that a visible error instead of a dead button.
 */
export async function renderGoogleButton(
  parent: HTMLElement,
  options: { theme: "outline" | "filled_black"; locale?: string },
): Promise<OAuthResult> {
  if (!GOOGLE_CLIENT_ID) throw new Error("Google sign-in is not configured");
  await loadScript(GOOGLE_SRC);

  const google = window.google;
  if (!google) throw new Error("Google sign-in failed to load");

  const nonce = makeNonce();

  return new Promise<OAuthResult>((resolve, reject) => {
    google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      nonce,
      use_fedcm_for_prompt: true,
      callback: (response) => {
        if (!response.credential) {
          reject(new Error("Google returned no credential"));
          return;
        }
        resolve({ idToken: response.credential, nonce });
      },
    });

    google.accounts.id.renderButton(parent, {
      type: "icon",
      theme: options.theme,
      size: "large",
      shape: "square",
      locale: options.locale ?? "en",
    });
  });
}

// ---------------------------------------------------------------------- apple
/**
 * Opens Apple's popup and resolves with the ID token.
 *
 * `usePopup` keeps the user on the page. The redirect variant would work, but it means
 * losing whatever they had typed and handling a return trip through a route that exists
 * only for this.
 *
 * The name is present exactly once — on the very first authorisation for a given Apple
 * ID — and Apple never sends it again. It is forwarded so the backend can persist it at
 * that one opportunity.
 */
export async function signInWithApple(): Promise<OAuthResult> {
  if (!APPLE_SERVICE_ID) throw new Error("Apple sign-in is not configured");
  await loadScript(APPLE_SRC);

  const apple = window.AppleID;
  if (!apple) throw new Error("Apple sign-in failed to load");

  const nonce = makeNonce();

  apple.auth.init({
    clientId: APPLE_SERVICE_ID,
    scope: "name email",
    // Must exactly match a Return URL registered on the Apple Services ID, or Apple
    // rejects the request before the user sees anything.
    redirectURI: `${window.location.origin}/login`,
    usePopup: true,
    nonce,
  });

  const response = await apple.auth.signIn();
  const name = response.user?.name;
  const displayName = [name?.firstName, name?.lastName].filter(Boolean).join(" ").trim();

  return {
    idToken: response.authorization.id_token,
    nonce,
    displayName: displayName || undefined,
  };
}


/**
 * Click Google's rendered button on behalf of a custom one.
 *
 * Returns false when the target cannot be found, so the caller can say something rather
 * than presenting a button that silently does nothing. This is the fragile part of the
 * custom-mark approach and it is deliberately loud about failing.
 */
export function clickGoogleButton(container: HTMLElement | null): boolean {
  const target = container?.querySelector<HTMLElement>('div[role="button"]');
  if (!target) return false;
  target.click();
  return true;
}
