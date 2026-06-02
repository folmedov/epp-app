"""Route handlers for email subscription lifecycle.

Routes:
  POST /subscribe              — create unconfirmed subscription (redirects to /auth/register)
  GET  /confirm/{token}        — double opt-in confirmation (redirects to /auth/confirm/{token})
  GET  /unsubscribe/{token}    — one-click unsubscribe (permanent token, no auth required)
  POST /send-follow-link       — send a magic link with the unsubscribe token
  GET  /save-token/{token}     — save token to localStorage (redirects to /auth/magic-link/{token})
  POST /offers/{id}/follow     — follow an offer (auth via Bearer or ?token=)
  DELETE /offers/{id}/follow   — unfollow an offer (auth via Bearer or ?token=)
  GET  /offers/follows         — JSON partial of followed offers (auth via Bearer or ?token=)
  GET  /follows                — full dashboard page (auth via Bearer or ?token=)
  GET  /search-subscriptions   — manage search subscription terms (page)
  POST /search-subscriptions   — add a search term
  DELETE /search-subscriptions/{id} — remove a search term
  PATCH /search-subscriptions/{id}/toggle — toggle active state
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import JobOffer, OfferFollow, SearchSubscription, Subscription
from src.notifications.email import NotificationError, send_follow_link_email
from src.web.auth import get_optional_subscription
from src.web.deps import get_db_session
from src.web.queries import (
    get_followed_offers,
    get_followed_offer_ids,
    get_offers_by_terms,
)
from src.web.templating import templates

LOGGER = logging.getLogger(__name__)

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ── Legacy redirects ──────────────────────────────────────────────────────────


@router.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page_redirect() -> HTMLResponse:
    """Legacy subscribe page — redirect to /auth/register."""
    return RedirectResponse(url="/auth/register", status_code=302)


@router.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm_redirect(token: str) -> HTMLResponse:
    """Legacy confirm link — redirect to /auth/confirm/{token}."""
    return RedirectResponse(url=f"/auth/confirm/{token}", status_code=302)


@router.get("/save-token/{token}", response_class=HTMLResponse)
async def save_token_redirect(token: str) -> HTMLResponse:
    """Legacy save-token link — redirect to /auth/magic-link/{token}."""
    return RedirectResponse(url=f"/auth/magic-link/{token}", status_code=302)


# ── Unsubscribe ───────────────────────────────────────────────────────────────


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse:
    """Delete a subscription via the one-click unsubscribe link.

    Idempotent — returns a success page even if the token is not found.
    ON DELETE CASCADE removes all related rows automatically.
    """
    result = await session.execute(
        select(Subscription).where(
            Subscription.unsubscribe_token == token  # type: ignore[arg-type]
        )
    )
    subscription: Subscription | None = result.scalar_one_or_none()

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


# ── Offer following ───────────────────────────────────────────────────────────


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
                "error": "No encontramos una suscripcion confirmada con ese email. "
                "Registrate primero.",
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


@router.post("/offers/{offer_id}/follow")
async def follow_offer(
    offer_id: str,
    session: DbSession,
    sub: Subscription = Depends(get_optional_subscription),
) -> JSONResponse:
    """Follow a specific job offer."""
    if sub is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token invalido o sesion no encontrada."},
        )

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
    sub: Subscription = Depends(get_optional_subscription),
) -> JSONResponse:
    """Unfollow a specific job offer (idempotent)."""
    if sub is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token invalido o sesion no encontrada."},
        )

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
    sub: Subscription = Depends(get_optional_subscription),
) -> JSONResponse:
    """Return followed offers as JSON for HTMX."""
    if sub is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token invalido o sesion no encontrada."},
        )
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
    sub: Subscription = Depends(get_optional_subscription),
) -> HTMLResponse:
    """Full dashboard page showing all followed offers."""
    if sub is None:
        return templates.TemplateResponse(
            request,
            "follows.html",
            {
                "valid_token": False,
                "offers": [],
                "subscription": None,
                "token": "",
            },
        )
    offers = await get_followed_offers(session, sub.id)
    return templates.TemplateResponse(
        request,
        "follows.html",
        {
            "valid_token": True,
            "offers": offers,
            "subscription": sub,
            "token": str(sub.unsubscribe_token) if sub.unsubscribe_token else "",
            "email": sub.email,
        },
    )


# ── Search subscriptions ──────────────────────────────────────────────────────


@router.get("/search-subscriptions", response_class=HTMLResponse)
async def search_subscriptions_page(
    request: Request,
    session: DbSession,
    sub: Subscription = Depends(get_optional_subscription),
    page: int = 1,
) -> HTMLResponse:
    """Manage search subscription terms with matching results below."""
    if sub is None:
        return templates.TemplateResponse(
            request,
            "search_subscriptions.html",
            {
                "valid_token": False,
                "subscription": None,
                "terms": [],
                "offers": [],
                "total": 0,
                "term_counts": {},
                "token": "",
            },
        )

    result = await session.execute(
        select(SearchSubscription)
        .where(SearchSubscription.subscription_id == sub.id)
        .order_by(SearchSubscription.created_at.desc())
    )
    terms: list[SearchSubscription] = result.scalars().all()  # type: ignore[assignment]

    # Per-term result counts
    term_counts: dict[str, int] = {}
    for ss in terms:
        stmt = select(func.count()).select_from(JobOffer).where(
            func.unaccent(JobOffer.title).ilike(func.unaccent(f"%{ss.term}%")),
            JobOffer.state == "postulacion",
            JobOffer.is_active.is_(True),
        )
        cnt = await session.scalar(stmt)
        term_counts[ss.term] = int(cnt or 0)

    active_terms = [ss.term for ss in terms if ss.active]
    followed_ids = await get_followed_offer_ids(session, sub.id)
    offers, total = await get_offers_by_terms(
        session, active_terms, followed_ids=followed_ids, page=page,
    )

    return templates.TemplateResponse(
        request,
        "search_subscriptions.html",
        {
            "valid_token": True,
            "subscription": sub,
            "terms": terms,
            "offers": offers,
            "total": total,
            "term_counts": term_counts,
            "token": str(sub.unsubscribe_token) if sub.unsubscribe_token else "",
            "email": sub.email,
        },
    )


@router.post("/search-subscriptions")
async def add_search_term(
    request: Request,
    session: DbSession,
    sub: Subscription = Depends(get_optional_subscription),
    term: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Add a new search term for the current subscription."""
    if sub is None:
        return templates.TemplateResponse(
            request,
            "search_subscriptions.html",
            {
                "valid_token": False,
                "subscription": None,
                "terms": [],
                "token": "",
                "error": "Debes iniciar sesion para agregar busquedas.",
            },
        )

    term = term.strip().lower()
    if not term:
        return await search_subscriptions_page(request, session, sub)

    # Check for duplicates
    result = await session.execute(
        select(SearchSubscription).where(
            SearchSubscription.subscription_id == sub.id,
            SearchSubscription.term == term,
        )
    )
    if result.scalar_one_or_none() is None:
        ss = SearchSubscription(
            subscription_id=sub.id,
            term=term,
        )
        session.add(ss)
        await session.commit()

    return await search_subscriptions_page(request, session, sub)


@router.post("/search-subscriptions/{ss_id}/delete")
async def remove_search_term(
    request: Request,
    ss_id: str,
    session: DbSession,
    sub: Subscription = Depends(get_optional_subscription),
) -> HTMLResponse:
    """Remove a search term."""
    if sub is None:
        return HTMLResponse(status_code=401, content="No autorizado")

    result = await session.execute(
        select(SearchSubscription).where(
            SearchSubscription.id == ss_id,
            SearchSubscription.subscription_id == sub.id,
        )
    )
    ss = result.scalar_one_or_none()
    if ss is not None:
        await session.delete(ss)
        await session.commit()

    return await search_subscriptions_page(request, session, sub)


@router.post("/search-subscriptions/{ss_id}/toggle")
async def toggle_search_term(
    request: Request,
    ss_id: str,
    session: DbSession,
    sub: Subscription = Depends(get_optional_subscription),
) -> HTMLResponse:
    """Toggle a search term's active state."""
    if sub is None:
        return HTMLResponse(status_code=401, content="No autorizado")

    result = await session.execute(
        select(SearchSubscription).where(
            SearchSubscription.id == ss_id,
            SearchSubscription.subscription_id == sub.id,
        )
    )
    ss = result.scalar_one_or_none()
    if ss is not None:
        ss.active = not ss.active
        await session.commit()

    return await search_subscriptions_page(request, session, sub)
