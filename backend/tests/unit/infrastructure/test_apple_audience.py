"""The Apple verifier's audience configuration.

Apple sets the `aud` claim to a different value per platform: a native iOS app gets the
**bundle identifier**, and the web flow gets the **Services ID**. They are unrelated
strings.

A verifier that knows only one of them rejects every sign-in from the other platform with
an invalid-token error that names no cause — the app simply refuses to sign anybody in,
and the reason is a config value nobody thought to look at. These tests exist so that
configuration cannot silently regress to a single audience.
"""

from __future__ import annotations

from coresync.core.config import Settings
from coresync.infrastructure.external.oidc import AppleOidcVerifier


def verifier(*, service_id: str = "", bundle_id: str = "") -> AppleOidcVerifier:
    settings = Settings(apple_service_id=service_id, apple_bundle_id=bundle_id)
    return AppleOidcVerifier(settings)


class TestAudiences:
    def test_accepts_both_the_web_and_the_native_audience(self) -> None:
        subject = verifier(service_id="ai.coresync.web", bundle_id="ai.coresync.app")

        assert set(subject._audiences) == {"ai.coresync.web", "ai.coresync.app"}

    def test_native_alone_is_enough_for_an_ios_only_deployment(self) -> None:
        subject = verifier(bundle_id="ai.coresync.app")
        assert subject._audiences == ["ai.coresync.app"]

    def test_web_alone_is_enough_for_a_web_only_deployment(self) -> None:
        subject = verifier(service_id="ai.coresync.web")
        assert subject._audiences == ["ai.coresync.web"]

    def test_an_unset_audience_is_not_carried_as_an_empty_string(self) -> None:
        # An empty audience in the list would be compared against the token's `aud` and
        # could never match, but it would also stop the "not configured" check firing —
        # turning a clear configuration error into a confusing rejection.
        subject = verifier(bundle_id="ai.coresync.app")
        assert "" not in subject._audiences

    def test_reports_being_unconfigured_rather_than_rejecting_tokens(self) -> None:
        # With neither value set, Apple sign-in is off. That has to be distinguishable
        # from "the token was bad", because the fix is completely different.
        subject = verifier()
        assert subject._audiences == []
