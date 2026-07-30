"""Email adapters.

Phase 1 sends inline — the volume is trivial and the failure mode (a verification email
arrives a second late) is benign. Phase 6 moves these onto the transactional outbox so
delivery survives a crash and can be retried.
"""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from coresync.core.config import Settings
from coresync.core.logging import get_logger

logger = get_logger(__name__)


_BASE_STYLE = (
    "font-family:-apple-system,'Segoe UI',sans-serif;max-width:520px;margin:0 auto;"
    "padding:32px 24px;color:#0b0b0b;line-height:1.6"
)
_BUTTON_STYLE = (
    "display:inline-block;background:#c8ff3d;color:#0f0f11;text-decoration:none;"
    "padding:14px 28px;border-radius:12px;font-weight:600;margin:20px 0"
)


def _wrap(title: str, body_html: str) -> str:
    return f"""
    <div style="{_BASE_STYLE}">
      <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em">{title}</h1>
      {body_html}
      <hr style="border:none;border-top:1px solid #e1e0d9;margin:32px 0">
      <p style="font-size:13px;color:#898781">
        CoreSync · You received this because someone used this address to sign up.
      </p>
    </div>
    """


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _send(self, *, to: str, subject: str, html: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_username or None,
                password=self._settings.smtp_password or None,
                start_tls=self._settings.smtp_use_tls,
                timeout=10,
            )
            logger.info("email_sent", subject=subject, email=to)
        except Exception:
            # A failed email must not fail the request that triggered it — the user has
            # already been created, and "resend verification" exists for this case.
            logger.exception("email_send_failed", subject=subject, email=to)

    async def send_verification(self, *, to: str, name: str, verify_url: str) -> None:
        await self._send(
            to=to,
            subject="Verify your email · CoreSync",
            html=_wrap(
                f"Welcome, {name}",
                f"<p>Confirm your email to unlock your AI coach and keep your account "
                f'secure.</p><a href="{verify_url}" style="{_BUTTON_STYLE}">Verify email</a>'
                f'<p style="font-size:13px;color:#52514e">This link expires in 24 hours.</p>',
            ),
            text=f"Welcome, {name}. Verify your email: {verify_url} (expires in 24 hours)",
        )

    async def send_password_reset(self, *, to: str, name: str, reset_url: str) -> None:
        await self._send(
            to=to,
            subject="Reset your password · CoreSync",
            html=_wrap(
                "Reset your password",
                f"<p>Hi {name}, use the button below to choose a new password.</p>"
                f'<a href="{reset_url}" style="{_BUTTON_STYLE}">Reset password</a>'
                f'<p style="font-size:13px;color:#52514e">This link expires in 30 minutes. '
                f"If you didn't request it, you can ignore this email — nothing has "
                f"changed.</p>",
            ),
            text=f"Reset your CoreSync password: {reset_url} (expires in 30 minutes)",
        )

    async def send_password_changed(self, *, to: str, name: str) -> None:
        await self._send(
            to=to,
            subject="Your password was changed · CoreSync",
            html=_wrap(
                "Your password was changed",
                f"<p>Hi {name}, your CoreSync password was just changed and all other "
                f"sessions were signed out.</p>"
                f"<p><strong>If this wasn't you</strong>, reset your password "
                f'immediately at <a href="{{reset}}">coresync.ai</a>.</p>',
            ),
            text="Your CoreSync password was changed. If this wasn't you, reset it now.",
        )

    async def send_account_exists_notice(self, *, to: str, sign_in_url: str) -> None:
        await self._send(
            to=to,
            subject="Someone tried to sign up with your email · CoreSync",
            html=_wrap(
                "You already have an account",
                f"<p>Someone tried to create a CoreSync account with this address. "
                f"You already have one — sign in instead, or reset your password if "
                f"you have forgotten it.</p>"
                f'<a href="{sign_in_url}" style="{_BUTTON_STYLE}">Sign in</a>',
            ),
            text=f"You already have a CoreSync account. Sign in: {sign_in_url}",
        )


class ConsoleEmailSender:
    """Development and test sender. Records what would have been sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def _record(self, kind: str, to: str, **fields: str) -> None:
        entry = {"kind": kind, "to": to, **fields}
        self.sent.append(entry)
        logger.info("email_captured", **entry)

    async def send_verification(self, *, to: str, name: str, verify_url: str) -> None:
        await self._record("verification", to, name=name, url=verify_url)

    async def send_password_reset(self, *, to: str, name: str, reset_url: str) -> None:
        await self._record("password_reset", to, name=name, url=reset_url)

    async def send_password_changed(self, *, to: str, name: str) -> None:
        await self._record("password_changed", to, name=name)

    async def send_account_exists_notice(self, *, to: str, sign_in_url: str) -> None:
        await self._record("account_exists", to, url=sign_in_url)
