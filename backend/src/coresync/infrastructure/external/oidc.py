"""Google and Apple ID-token verification.

Verification happens here, server-side, against the provider's published JWKS. The
client only ever forwards the token — a client-side "this is valid" would let anyone
sign in as anyone with a hand-crafted request.
"""

from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWKClient

from coresync.application.common.ports import OidcIdentity
from coresync.core.config import Settings
from coresync.core.errors import InvalidTokenError, UpstreamUnavailableError
from coresync.core.logging import get_logger

logger = get_logger(__name__)

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


class _JwksCache:
    """Caches the provider's signing keys.

    PyJWKClient caches internally, but a wrapper keeps the refresh policy explicit and
    gives one place to handle a provider being unreachable.
    """

    def __init__(self, url: str, ttl_seconds: int = 86_400) -> None:
        self._client = PyJWKClient(url, cache_keys=True, lifespan=ttl_seconds)
        self._url = url

    def signing_key(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except Exception as exc:
            logger.warning("jwks_fetch_failed", url=self._url, error=str(exc))
            raise UpstreamUnavailableError("could not fetch provider signing keys") from exc


class GoogleOidcVerifier:
    """Sign in with Google.

    Google issues a distinct OAuth client id per platform — Web, iOS and Android — and
    stamps whichever one requested the token into the `aud` claim. All configured ids are
    therefore accepted; knowing only the web one means every sign-in from a phone is
    refused as an invalid token, with nothing in the message to say why.
    """

    def __init__(self, settings: Settings) -> None:
        self._audiences = [
            value
            for value in (
                settings.google_oauth_client_id,
                settings.google_ios_client_id,
                settings.google_android_client_id,
            )
            if value
        ]
        self._jwks = _JwksCache(GOOGLE_JWKS_URL)

    async def verify(self, id_token: str, *, nonce: str | None = None) -> OidcIdentity:
        if not self._audiences:
            raise InvalidTokenError("Google sign-in is not configured")

        key = self._jwks.signing_key(id_token)
        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self._audiences,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError(f"invalid Google token: {exc}") from exc

        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise InvalidTokenError("unexpected issuer")
        if nonce is not None and claims.get("nonce") != nonce:
            # Binds the token to this sign-in attempt, defeating replay.
            raise InvalidTokenError("nonce mismatch")

        return OidcIdentity(
            subject=claims["sub"],
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name"),
            provider="google",
        )


class AppleOidcVerifier:
    """Apple Sign In.

    Three behaviours worth knowing about, all of which cause bugs if ignored:
    the user's name is returned only on the *first* authorisation and never again;
    "Hide My Email" yields a `@privaterelay.appleid.com` address that only delivers if
    the sending domain is registered with Apple; and the `aud` claim differs by platform,
    which is why two audiences are accepted rather than one.
    """

    def __init__(self, settings: Settings) -> None:
        # Both audiences, because Apple issues a different one per platform: the web flow
        # gets the Services ID and a native iOS app gets its bundle identifier. Accepting
        # only one silently rejects every sign-in from the other.
        self._audiences = [
            value for value in (settings.apple_service_id, settings.apple_bundle_id) if value
        ]
        self._jwks = _JwksCache(APPLE_JWKS_URL)

    async def verify(self, id_token: str, *, nonce: str | None = None) -> OidcIdentity:
        if not self._audiences:
            raise InvalidTokenError("Apple sign-in is not configured")

        key = self._jwks.signing_key(id_token)
        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=APPLE_ISSUER,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError(f"invalid Apple token: {exc}") from exc

        if nonce is not None and claims.get("nonce") != nonce:
            raise InvalidTokenError("nonce mismatch")

        email_verified = claims.get("email_verified")
        if isinstance(email_verified, str):  # Apple sometimes sends "true" as a string
            email_verified = email_verified.lower() == "true"

        return OidcIdentity(
            subject=claims["sub"],
            email=claims.get("email"),
            email_verified=bool(email_verified),
            name=None,  # never present in the token; the client forwards it separately
            provider="apple",
        )


class FakeOidcVerifier:
    """Test double. Accepts a JSON-ish token so tests never touch the network."""

    def __init__(self, identity: OidcIdentity | None = None) -> None:
        self.identity = identity

    async def verify(self, id_token: str, *, nonce: str | None = None) -> OidcIdentity:
        if self.identity is None:
            raise InvalidTokenError("no fake identity configured")
        if id_token == "invalid":
            raise InvalidTokenError("fake rejection")
        return self.identity
