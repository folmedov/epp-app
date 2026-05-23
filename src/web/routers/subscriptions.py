"""Route handlers for email subscription lifecycle.

Routes:
  POST /subscribe              — create unconfirmed subscription + send confirmation email
  GET  /confirm/{token}        — double opt-in confirmation (single-use token, 24h expiry)
  GET  /unsubscribe/{token}    — one-click unsubscribe (permanent token, no auth required)
  POST /send-follow-link       — send a magic link with the unsubscribe token
  GET  /save-token/{token}     — save token to localStorage (magic link landing page)
  POST /offers/{id}/follow     — follow an offer (auth via ?token=)
  DELETE /offers/{id}/follow   — unfollow an offer (auth via ?token=)
  GET  /offers/follows         — JSON partial of followed offers (auth via ?token=)
  GET  /follows                — full dashboard page of followed offers (auth via ?token=)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import OfferFollow, Subscription
from src.notifications.email import NotificationError, send_confirmation_email, send_follow_link_email
from src.web.deps import get_db_session
from src.web.queries import (
    get_followed_offers,
    get_subscription_by_token,
)
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
) -> HTMLResponse:
    """Create an unconfirmed subscription and send a confirmation email."""
    email = email.strip().lower()

    if not email:
        error = "Por favor ingresa un email."
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
        existing.confirmation_token = uuid4()
        existing.token_expires_at = datetime.utcnow() + timedelta(hours=24)
        await session.commit()
        subscription = existing
    else:
        subscription = Subscription(
            email=email,
            confirmed=False,
            confirmation_token=uuid4(),
            token_expires_at=datetime.utcnow() + timedelta(hours=24),
            unsubscribe_token=None,
        )
        session.add(subscription)
        await session.commit()

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

    unsubscribe_token: UUID = subscription.unsubscribe_token  # type: ignore[assignment]

    await session.commit()

    # Redirect to save-token so the token is stored in localStorage
    return RedirectResponse(
        url=f"/save-token/{unsubscribe_token}",
        status_code=302,
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


# ── Welcome notification (simplified — no keyword matching) ────────────────────

# No welcome notification is sent on confirmation. The user is redirected to
# /save-token/{token} which stores their token and redirects to /follows.


# ── Offer following ────────────────────────────────────────────────────────────


@router.post("/send-follow-link", response_class=HTMLResponse)
async def send_follow_link(
    request: Request,
    session: DbSession,
    email: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Send a magic link with the unsubscribe token to the given email.

    If the email has a confirmed subscription, sends the token link.
    If not, returns a friendly error.
    """
    email = email.strip().lower()
    if not email:
        return templates.TemplateResponse(
            request,
            "follow_link_sent.html",
            {"error": "Por favor ingresa un email."},
        )

    result = await session.execute(
        select(Subscription).where(
            Subscription.email == email,
            Subscription.confirmed.is_(True),
        )
    )
    sub = result.scalar_one_or_none()

    if sub is None or sub.unsubscribe_token is None:
        return templates.TemplateResponse(
            request,
            "follow_link_sent.html",
            {
                "error": "No encontramos una suscripción confirmada con ese email. "
                "Suscríbete primero en la página de Alertas.",
            },
        )

    try:
        await send_follow_link_email(
            email=str(sub.email),
            token=str(sub.unsubscribe_token),
        )
    except NotificationError as exc:
        LOGGER.error("Failed to send follow link email to %s: %s", email, exc)

    return templates.TemplateResponse(
        request,
        "follow_link_sent.html",
        {"error": None},
    )


@router.get("/save-token/{token}", response_class=HTMLResponse)
async def save_token_page(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse:
    """Landing page for the magic link — saves token to localStorage via JS."""
    sub = await get_subscription_by_token(session, token)
    if sub is None:
        return templates.TemplateResponse(
            request,
            "save_token.html",
            {"valid": False, "token": None},
        )
    return templates.TemplateResponse(
        request,
        "save_token.html",
        {"valid": True, "token": token},
    )


def _require_subscription(sub: Subscription | None) -> JSONResponse | None:
    """Return a 401 JSON response if subscription is invalid, else None."""
    if sub is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token inválido o suscripción no encontrada."},
        )
    return None


@router.post("/offers/{offer_id}/follow")
async def follow_offer(
    offer_id: str,
    session: DbSession,
    token: str = Query(...),
) -> JSONResponse:
    """Follow a specific job offer."""
    sub = await get_subscription_by_token(session, token)
    if (err := _require_subscription(sub)) is not None:
        return err

    result = await session.execute(
        select(OfferFollow).where(
            OfferFollow.subscription_id == sub.id,
            OfferFollow.job_offer_id == offer_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        follow = OfferFollow(
            subscription_id=sub.id,
            job_offer_id=offer_id,
        )
        session.add(follow)
        await session.commit()

    return JSONResponse(content={"followed": True})


@router.delete("/offers/{offer_id}/follow")
async def unfollow_offer(
    offer_id: str,
    session: DbSession,
    token: str = Query(...),
) -> JSONResponse:
    """Unfollow a specific job offer (idempotent)."""
    sub = await get_subscription_by_token(session, token)
    if (err := _require_subscription(sub)) is not None:
        return err

    result = await session.execute(
        select(OfferFollow).where(
            OfferFollow.subscription_id == sub.id,
            OfferFollow.job_offer_id == offer_id,
        )
    )
    follow = result.scalar_one_or_none()
    if follow is not None:
        await session.delete(follow)
        await session.commit()

    return JSONResponse(content={"followed": False})


@router.get("/offers/follows", response_class=JSONResponse)
async def followed_offers_json(
    session: DbSession,
    token: str = Query(...),
) -> JSONResponse:
    """Return followed offers as JSON for HTMX."""
    sub = await get_subscription_by_token(session, token)
    if (err := _require_subscription(sub)) is not None:
        return err
    offers = await get_followed_offers(session, sub.id)
    return JSONResponse(
        content={
            "offers": [
                {
                    "id": str(o.id),
                    "title": o.title,
                    "institution": o.institution,
                    "state": o.state,
                    "close_date": str(o.close_date) if o.close_date else None,
                    "url": o.url,
                }
                for o in offers
            ]
        }
    )


@router.get("/follows", response_class=HTMLResponse)
async def follows_dashboard(
    request: Request,
    session: DbSession,
    token: str = Query(...),
) -> HTMLResponse:
    """Full dashboard page showing all followed offers."""
    sub = await get_subscription_by_token(session, token)
    if sub is None:
        return templates.TemplateResponse(
            request,
            "follows.html",
            {"valid_token": False, "offers": []},
        )
    offers = await get_followed_offers(session, sub.id)
    return templates.TemplateResponse(
        request,
        "follows.html",
        {
            "valid_token": True,
            "offers": offers,
            "token": token,
            "email": sub.email,
        },
    )
