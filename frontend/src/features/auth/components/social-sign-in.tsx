"use client";

import { useEffect, useRef, useState } from "react";

import { authApi } from "@/features/auth/api";
import {
  APPLE_SERVICE_ID,
  GOOGLE_CLIENT_ID,
  isConfigured,
  renderGoogleButton,
  signInWithApple,
  type OAuthResult,
} from "@/features/auth/oauth-providers";
import { useAuthStore } from "@/features/auth/store";
import { ApiError } from "@/lib/api/client";
import { useTheme } from "next-themes";

type Props = {
  onSuccess: () => void;
  /** Shown above the buttons. Omitted when neither provider is configured. */
  dividerLabel?: string;
};

/**
 * Google and Apple sign-in.
 *
 * Renders nothing at all when neither provider has a client ID configured, rather than
 * showing buttons that fail on click. A deployment without credentials is a normal
 * state — local development, most of the time — and a dead button is worse than an
 * absent one.
 */
export function SocialSignIn({ onSuccess, dividerLabel = "or" }: Props) {
  const googleSlot = useRef<HTMLDivElement>(null);
  const signIn = useAuthStore((state) => state.signIn);
  const { resolvedTheme } = useTheme();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const hasGoogle = isConfigured("google");
  const hasApple = isConfigured("apple");

  async function exchange(provider: "google" | "apple", result: OAuthResult) {
    setBusy(true);
    setError(null);
    try {
      const tokens = await authApi.oauthSignIn(provider, {
        idToken: result.idToken,
        nonce: result.nonce,
        displayName: result.displayName,
      });
      signIn(tokens.user, tokens.accessToken);
      onSuccess();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "That didn't work. Try again in a moment.",
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!hasGoogle || !googleSlot.current) return;
    let cancelled = false;

    // Google renders its own button and resolves through a callback rather than a
    // click handler, so the promise is set up once when the slot mounts.
    renderGoogleButton(googleSlot.current, {
      theme: resolvedTheme === "light" ? "outline" : "filled_black",
    })
      .then((result) => {
        if (!cancelled) void exchange("google", result);
      })
      .catch(() => {
        if (!cancelled) setError("Google sign-in is unavailable right now.");
      });

    return () => {
      cancelled = true;
    };
    // Re-rendered on theme change so the mark matches the page it sits on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasGoogle, resolvedTheme]);

  if (!hasGoogle && !hasApple) return null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3" aria-hidden>
        <span className="h-px flex-1 bg-border" />
        <span className="text-caption text-text-muted">{dividerLabel}</span>
        <span className="h-px flex-1 bg-border" />
      </div>

      {error && (
        <p role="alert" className="text-caption text-critical">
          {error}
        </p>
      )}

      {/* Marks only, side by side. Both squares are 44pt so they clear the touch
          target floor — an icon button that is merely icon-sized is the classic way to
          make something unusable on a phone. */}
      <div className="flex items-center justify-center gap-3">
        {hasGoogle && (
          // Google's own rendered mark, not a hand-drawn one: their branding terms
          // require it, and it is also what gets FedCM and One Tap. Their icon button
          // renders at 40px, so the wrapper squares it up to 44.
          <div
            ref={googleSlot}
            className="h-11 w-11 overflow-hidden rounded-md [&_div[role=button]]:!h-11 [&_div[role=button]]:!w-11 [&_div[role=button]]:!rounded-md [&_iframe]:!h-11 [&_iframe]:!w-11"
          />
        )}

        {hasApple && (
          <button
            type="button"
            disabled={busy}
            // The label carries what the mark no longer says. Without it a screen
            // reader announces "button" and nothing else.
            aria-label="Continue with Apple"
            onClick={() => {
              void signInWithApple()
                .then((result) => exchange("apple", result))
                .catch(() => {
                  // A closed popup is not an error worth shouting about — the user
                  // changed their mind, which is a normal thing to do.
                });
            }}
            className="flex h-11 w-11 items-center justify-center rounded-md border border-border bg-surface-raised text-text transition-colors hover:bg-surface-well disabled:opacity-50"
          >
            <AppleMark />
          </button>
        )}
      </div>
    </div>
  );
}

function AppleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 fill-current" aria-hidden focusable="false">
      <path d="M16.365 1.43c0 1.14-.42 2.2-1.25 3.02-.99.99-2.1 1.56-3.3 1.47a3.3 3.3 0 0 1-.03-.6c0-1.1.5-2.27 1.31-3.07.8-.8 2.06-1.4 3.13-1.45.03.21.14.42.14.63ZM20.9 17.1c-.55 1.27-.82 1.84-1.53 2.96-.99 1.57-2.39 3.53-4.12 3.54-1.54.02-1.94-1-4.03-.99-2.09.01-2.53 1.01-4.07.99-1.73-.01-3.05-1.78-4.04-3.35C.35 15.85-.02 10.7 2.1 8c1.03-1.35 2.65-2.14 4.18-2.14 1.56 0 2.54 1 3.83 1 1.25 0 2.01-1 3.81-1 1.36 0 2.8.74 3.83 2.02-3.37 1.85-2.82 6.66.15 8.22Z" />
    </svg>
  );
}

export { GOOGLE_CLIENT_ID, APPLE_SERVICE_ID };
