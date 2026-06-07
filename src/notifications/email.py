"""Async email sender for job offer notifications.

Public interface:
- send_confirmation_email(email, token) — double opt-in confirmation
- send_state_change_email(...) — state-change alert for followed offers
- send_follow_link_email(email, token) — magic link with unsubscribe token
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING

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

    confirm_url = f"{settings.APP_BASE_URL}/auth/confirm/{token}"
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


def check_smtp_config() -> None:
    """Public wrapper for SMTP config validation.

    Raises:
        NotificationError: If any required SMTP env var is missing.
    """
    _check_smtp_config()


async def send_state_change_email(
    email: str,
    offer: OfferRow,
    unsubscribe_token: str,
    old_state: str,
    new_state: str,
) -> None:
    """Send a state-change notification for a followed offer.

    Args:
        email: Recipient email address.
        offer: The followed offer.
        unsubscribe_token: Unsubscribe token (UUID string).
        old_state: Previous state.
        new_state: Current (new) state.

    Raises:
        NotificationError: If SMTP is not configured or the send fails.
    """
    _check_smtp_config()

    unsubscribe_url = f"{settings.APP_BASE_URL}/unsubscribe/{unsubscribe_token}"
    follows_url = f"{settings.APP_BASE_URL}/follows?token={unsubscribe_token}"
    context = {
        "offer": offer,
        "old_state": old_state,
        "new_state": new_state,
        "unsubscribe_url": unsubscribe_url,
        "follows_url": follows_url,
        "base_url": settings.APP_BASE_URL,
    }

    html_body = _render_template("state_change_email.html", context)
    plain_body = _render_template("state_change_email.txt", context)

    msg = _build_message(
        to_email=email,
        subject=f"Estado actualizado: {offer.title} ahora está «{new_state}»",
        html_body=html_body,
        plain_body=plain_body,
    )

    LOGGER.info("Sending state-change email to %s for '%s'", email, offer.title)
    await _send(msg)
    LOGGER.info("State-change email sent to %s", email)


async def send_follow_link_email(email: str, token: str) -> None:
    """Send an email with a magic link to save the unsubscribe token.

    Args:
        email: Recipient email address.
        token: Unsubscribe token (UUID string).

    Raises:
        NotificationError: If SMTP is not configured or the send fails.
    """
    _check_smtp_config()

    save_url = f"{settings.APP_BASE_URL}/auth/magic-link/{token}"
    context = {
        "save_url": save_url,
        "base_url": settings.APP_BASE_URL,
    }

    html_body = _render_template("follow_link_email.html", context)
    plain_body = _render_template("follow_link_email.txt", context)

    msg = _build_message(
        to_email=email,
        subject="Accede a tus ofertas seguidas — Job Tracker",
        html_body=html_body,
        plain_body=plain_body,
    )

    LOGGER.info("Sending follow link email to %s", email)
    await _send(msg)
    LOGGER.info("Follow link email sent to %s", email)


async def send_search_match_email(
    email: str,
    matches: list[tuple[OfferRow, str]],
    unsubscribe_token: str,
) -> None:
    """Send a digest notification with all offers matching subscribed terms.

    Args:
        email: Recipient email address.
        matches: List of (offer, term) tuples that matched in this run.
        unsubscribe_token: Unsubscribe token (UUID string).

    Raises:
        NotificationError: If SMTP is not configured or the send fails.
    """
    _check_smtp_config()

    unsubscribe_url = f"{settings.APP_BASE_URL}/unsubscribe/{unsubscribe_token}"
    search_url = f"{settings.APP_BASE_URL}/search-subscriptions?token={unsubscribe_token}"
    match_list = [{"offer": o, "term": t} for o, t in matches]
    context = {
        "matches": match_list,
        "total": len(match_list),
        "unsubscribe_url": unsubscribe_url,
        "search_url": search_url,
        "base_url": settings.APP_BASE_URL,
    }

    html_body = _render_template("search_match_email.html", context)
    plain_body = _render_template("search_match_email.txt", context)

    subject = f"{len(matches)} nueva{'s' if len(matches) != 1 else ''} oferta{'s' if len(matches) != 1 else ''} en tus búsquedas"
    msg = _build_message(
        to_email=email,
        subject=subject,
        html_body=html_body,
        plain_body=plain_body,
    )

    LOGGER.info("Sending search-match digest to %s (%d match(es))", email, len(matches))
    await _send(msg)
    LOGGER.info("Search-match digest sent to %s", email)


__all__ = [
    "NotificationError",
    "OfferRow",
    "check_smtp_config",
    "send_confirmation_email",
    "send_follow_link_email",
    "send_state_change_email",
    "send_search_match_email",
]
