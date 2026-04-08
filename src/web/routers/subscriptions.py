"""Route handlers for email subscription lifecycle.

Routes:
  POST /subscribe         — create unconfirmed subscription + send confirmation email
  GET  /confirm/{token}   — double opt-in confirmation (single-use token, 24h expiry)
  GET  /unsubscribe/{token} — one-click unsubscribe (permanent token, no auth required)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Subscription
from src.notifications.email import NotificationError, send_confirmation_email
from src.web.deps import get_db_session
from src.web.templating import templates

LOGGER = logging.getLogger(__name__)

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(request: Request) -> HTMLResponse:
    """Render the subscribe form."""
    return templates.TemplateResponse(
        request,
        "subscribe.html",
        {"submitted": False, "error": None},
    )


@router.post("/subscribe", response_class=HTMLResponse)
async def subscribe(
    request: Request,
    session: DbSession,
    email: Annotated[str, Form()] = "",
    keywords: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Create an unconfirmed subscription and send a confirmation email."""
    # Normalise inputs
    email = email.strip().lower()
    keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]

    # Validation
    if not email or not keyword_list:
        error = "Por favor ingresa un email y al menos una palabra clave."
        return templates.TemplateResponse(
            request,
            "subscribe.html",
            {"submitted": False, "error": error},
        )

    # Look up any existing subscription for this email
    result = await session.execute(
        select(Subscription).where(Subscription.email == email)
    )
    existing: Optional[Subscription] = result.scalar_one_or_none()

    if existing is not None and existing.confirmed:
        return templates.TemplateResponse(
            request,
            "subscribe.html",
            {"submitted": False, "error": "Ya estás suscrito/a con este email."},
        )

    if existing is not None and not existing.confirmed:
        # Regenerate token for users who lost the first confirmation email
        existing.keywords = keyword_list
        existing.confirmation_token = uuid4()
        existing.token_expires_at = datetime.utcnow() + timedelta(hours=24)
        await session.commit()
        subscription = existing
    else:
        subscription = Subscription(
            email=email,
            keywords=keyword_list,
            confirmed=False,
            confirmation_token=uuid4(),
            token_expires_at=datetime.utcnow() + timedelta(hours=24),
            unsubscribe_token=None,
        )
        session.add(subscription)
        await session.commit()

    # Send confirmation email (non-fatal if SMTP is not configured)
    try:
        await send_confirmation_email(email, str(subscription.confirmation_token))
    except NotificationError as exc:
        LOGGER.error("Failed to send confirmation email to %s: %s", email, exc)

    return templates.TemplateResponse(
        request,
        "subscribe.html",
        {"submitted": True, "error": None},
    )


@router.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm_subscription(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse:
    """Confirm a subscription via the double opt-in link.

    The confirmation token is single-use and valid for 24 hours.
    """
    result = await session.execute(
        select(Subscription).where(
            Subscription.confirmation_token == token  # type: ignore[arg-type]
        )
    )
    subscription: Optional[Subscription] = result.scalar_one_or_none()

    if subscription is None or (
        subscription.token_expires_at is not None
        and subscription.token_expires_at < datetime.utcnow()
    ):
        return templates.TemplateResponse(
            request,
            "confirm_ok.html",
            {
                "success": False,
                "message": "El enlace de confirmación no es válido o ha expirado. "
                "Vuelve a completar el formulario para recibir un nuevo enlace.",
            },
        )

    subscription.confirmed = True
    subscription.confirmation_token = None
    subscription.token_expires_at = None
    subscription.unsubscribe_token = uuid4()
    await session.commit()

    return templates.TemplateResponse(
        request,
        "confirm_ok.html",
        {"success": True, "message": "Tu suscripción ha sido confirmada."},
    )


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse:
    """Delete a subscription via the one-click unsubscribe link.

    Idempotent — returns a success page even if the token is not found.
    ON DELETE CASCADE removes all pending notification_queue rows automatically.
    """
    result = await session.execute(
        select(Subscription).where(
            Subscription.unsubscribe_token == token  # type: ignore[arg-type]
        )
    )
    subscription: Optional[Subscription] = result.scalar_one_or_none()

    if subscription is None:
        return templates.TemplateResponse(
            request,
            "unsubscribe_ok.html",
            {"already_removed": True},
        )

    await session.delete(subscription)
    await session.commit()

    return templates.TemplateResponse(
        request,
        "unsubscribe_ok.html",
        {"already_removed": False},
    )
