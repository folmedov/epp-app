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
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import ARRAY, String, bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Subscription
from src.notifications.email import (
    NotificationError,
    OfferRow,
    send_confirmation_email,
    send_notification_email,
)
from src.web.deps import get_db_session
from src.web.templating import templates

LOGGER = logging.getLogger(__name__)

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# ── SQL for welcome notification ──────────────────────────────────────────────

_WELCOME_MATCH_SQL = text("""
    SELECT jo.id, jo.title, jo.institution, jo.region, jo.close_date, jo.url
    FROM   job_offers jo
    JOIN   LATERAL unnest(:keywords) AS kw ON TRUE
    WHERE  jo.is_active = TRUE
      AND  jo.state = 'postulacion'
      AND  unaccent(jo.title) ILIKE unaccent('%' || kw || '%')
    GROUP  BY jo.id, jo.title, jo.institution, jo.region, jo.close_date, jo.url
""").bindparams(bindparam("keywords", type_=ARRAY(String())))

_WELCOME_QUEUE_INSERT_SQL = text("""
    INSERT INTO notification_queue
        (id, subscription_id, job_offer_id, notification_type, status)
    VALUES
        (:id, :subscription_id, :job_offer_id, 'immediate', 'pending')
    ON CONFLICT ON CONSTRAINT uq_notification_queue_dedup DO NOTHING
""")

_WELCOME_MARK_SENT_SQL = text("""
    UPDATE notification_queue
    SET    status = 'sent', sent_at = NOW()
    WHERE  subscription_id = :subscription_id
      AND  job_offer_id = ANY(:offer_ids)
      AND  notification_type = 'immediate'
      AND  status = 'pending'
""")


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

    # Capture values before commit — ORM expires attributes after session.commit()
    sub_id: UUID = subscription.id
    sub_email: str = subscription.email
    sub_keywords: list[str] = list(subscription.keywords)
    unsubscribe_token: UUID = subscription.unsubscribe_token  # type: ignore[assignment]

    await session.commit()

    # Send welcome notification with currently matching offers (non-fatal)
    try:
        await _send_welcome_notification(
            session, sub_id, sub_email, sub_keywords, unsubscribe_token
        )
    except Exception as exc:
        LOGGER.error("Unexpected error in welcome notification for %s: %s", sub_email, exc)

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


# ── Welcome notification helper ───────────────────────────────────────────────

async def _send_welcome_notification(
    session: AsyncSession,
    sub_id: UUID,
    email: str,
    keywords: list[str],
    unsubscribe_token: UUID,
) -> None:
    """Send an immediate notification with currently matching offers on confirmation.

    Inserts notification_queue rows as 'pending', attempts the SMTP send, and
    marks them 'sent' on success. If SMTP fails, rows stay 'pending' so the
    daily cron retries on the next run.
    """
    result = await session.execute(_WELCOME_MATCH_SQL, {"keywords": keywords})
    rows = result.fetchall()

    if not rows:
        LOGGER.info("No matching offers found for new subscriber %s — skipping welcome email.", email)
        return

    offer_ids = [str(row.id) for row in rows]

    for row in rows:
        await session.execute(
            _WELCOME_QUEUE_INSERT_SQL,
            {
                "id": str(uuid4()),
                "subscription_id": str(sub_id),
                "job_offer_id": str(row.id),
            },
        )

    offer_list = [
        OfferRow(
            title=row.title,
            institution=row.institution,
            region=row.region or "",
            close_date=row.close_date,
            url=row.url or "",
        )
        for row in rows
    ]

    try:
        await send_notification_email(
            email=email,
            offers=offer_list,
            unsubscribe_token=str(unsubscribe_token),
            notification_type="immediate",
        )
        await session.execute(
            _WELCOME_MARK_SENT_SQL,
            {"subscription_id": str(sub_id), "offer_ids": offer_ids},
        )
        LOGGER.info("Sent welcome notification to %s with %d offer(s).", email, len(offer_list))
    except NotificationError as exc:
        LOGGER.warning(
            "Failed to send welcome notification to %s: %s — will retry on next cron run.", email, exc
        )

    await session.commit()
