"use client";

import { useEffect, useRef, useState } from "react";

import { authApi } from "@/features/auth/api";
import { AppleMark, GoogleMark } from "@/features/auth/components/provider-marks";
import {
  APPLE_SERVICE_ID,
  GOOGLE_CLIENT_ID,
  clickGoogleButton,
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
          <>
            {/* Google's real button, kept in the tree and visually hidden. It is the
                only supported source of an ID token from a click, so it has to exist —
                the visible button below forwards to it. `sr-only` rather than
                `display:none`, because a hidden element cannot be clicked. */}
            <div ref={googleSlot} className="sr-only" aria-hidden />

            <button
              type="button"
              disabled={busy}
              aria-label="Continue with Google"
              onClick={() => {
                if (!clickGoogleButton(googleSlot.current)) {
                  setError("Google sign-in is unavailable right now.");
                }
              }}
              className="flex h-11 w-11 items-center justify-center rounded-md border border-border bg-surface-raised transition-colors hover:bg-surface-well disabled:opacity-50"
            >
              <GoogleMark />
            </button>
          </>
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

export { GOOGLE_CLIENT_ID, APPLE_SERVICE_ID };
