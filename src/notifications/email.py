"""Async email sender for job offer notifications.

Public interface:
- send_confirmation_email(email, token) — double opt-in confirmation
- send_notification_email(email, offers, unsubscribe_token, notification_type) — offer alerts
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from src.core.config import settings

if TYPE_CHECKING:
    from datetime import datetime

LOGGER = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)


class NotificationError(Exception):
    """Raised when an email cannot be sent."""


class OfferRow:
    """Lightweight data container for a job offer passed to email templates."""

    __slots__ = ("title", "institution", "region", "close_date", "url")

    def __init__(
        self,
        title: str,
        institution: str,
        region: str,
        close_date: datetime | None,
        url: str,
    ) -> None:
        self.title = title
        self.institution = institution
        self.region = region
        self.close_date = close_date
        self.url = url


def _check_smtp_config() -> None:
    """Raise NotificationError immediately if SMTP is not fully configured."""
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", settings.SMTP_HOST),
            ("SMTP_USER", settings.SMTP_USER),
            ("SMTP_PASSWORD", settings.SMTP_PASSWORD),
            ("SMTP_FROM", settings.SMTP_FROM),
        )
        if not value
    ]
    if missing:
        raise NotificationError(
            f"SMTP not configured — missing env vars: {', '.join(missing)}"
        )


def _render_template(template_name: str, context: dict) -> str:
    """Render a Jinja2 template from the notifications templates directory."""
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


def _build_message(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM  # type: ignore[assignment]
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


async def _send(msg: MIMEMultipart) -> None:
    """Connect to SMTP and send a single message."""
    use_tls = settings.SMTP_PORT == 465
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,  # type: ignore[arg-type]
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=use_tls,
            start_tls=not use_tls,
        )
    except aiosmtplib.SMTPException as exc:
        raise NotificationError(f"SMTP send failed: {exc}") from exc


async def send_confirmation_email(email: str, token: str) -> None:
    """Send a double opt-in confirmation email.

    Args:
        email: Recipient email address.
        token: Confirmation token (UUID string).

    Raises:
        NotificationError: If SMTP is not configured or the send fails.
    """
    _check_smtp_config()

    confirm_url = f"{settings.APP_BASE_URL}/confirm/{token}"
    context = {
        "confirm_url": confirm_url,
        "base_url": settings.APP_BASE_URL,
    }

    html_body = _render_template("confirm_email.html", context)
    plain_body = _render_template("confirm_email.txt", context)

    msg = _build_message(
        to_email=email,
        subject="Confirma tu suscripción — Job Tracker",
        html_body=html_body,
        plain_body=plain_body,
    )

    LOGGER.info("Sending confirmation email to %s", email)
    await _send(msg)
    LOGGER.info("Confirmation email sent to %s", email)


async def send_notification_email(
    email: str,
    offers: list[OfferRow],
    unsubscribe_token: str,
    notification_type: Literal["immediate", "digest"],
) -> None:
    """Send an offer notification email (immediate or digest).

    Args:
        email: Recipient email address.
        offers: List of OfferRow instances to include.
        unsubscribe_token: Unsubscribe token (UUID string).
        notification_type: 'immediate' (single offer) or 'digest' (weekly batch).

    Raises:
        NotificationError: If SMTP is not configured or the send fails.
    """
    _check_smtp_config()

    unsubscribe_url = f"{settings.APP_BASE_URL}/unsubscribe/{unsubscribe_token}"
    context = {
        "offers": offers,
        "unsubscribe_url": unsubscribe_url,
        "base_url": settings.APP_BASE_URL,
    }

    if notification_type == "immediate":
        template_html = "notification_immediate.html"
        template_txt = "notification_immediate.txt"
        subject = f"Nueva oferta publicada — {offers[0].title}" if offers else "Nueva oferta publicada"
    else:
        template_html = "notification_digest.html"
        template_txt = "notification_digest.txt"
        subject = f"Resumen semanal — {len(offers)} oferta{'s' if len(offers) != 1 else ''} nueva{'s' if len(offers) != 1 else ''}"

    html_body = _render_template(template_html, context)
    plain_body = _render_template(template_txt, context)

    msg = _build_message(
        to_email=email,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
    )

    LOGGER.info(
        "Sending %s notification to %s (%d offer(s))",
        notification_type,
        email,
        len(offers),
    )
    await _send(msg)
    LOGGER.info("Notification email sent to %s", email)


__all__ = ["NotificationError", "OfferRow", "send_confirmation_email", "send_notification_email"]
