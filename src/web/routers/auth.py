"""Auth route handlers: register, login, logout, me, magic-link.

Endpoints:
  POST /auth/register              — subscribe with email (alias for /subscribe)
  POST /auth/login                 — send magic link with unsubscribe_token
  POST /auth/logout                — invalidate current token (Bearer)
  GET  /auth/me                    — return current user info (Bearer or ?token=)
  GET  /auth/confirm/{token}       — confirm subscription (redirect to /auth/magic-link/{token})
  GET  /auth/magic-link/{token}    — save token to localStorage, redirect to /
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Subscription
from src.notifications.email import (
    NotificationError,
    send_confirmation_email,
    send_follow_link_email,
)
from src.web.auth import get_current_subscription, get_optional_subscription
from src.web.deps import get_db_session
from src.web.templating import templates

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ── Register ──────────────────────────────────────────────────────────────────


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    """Render the registration form."""
    return templates.TemplateResponse(
        request,
        "register.html",
        {"submitted": False, "error": None},
    )


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    session: DbSession,
    email: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Create an unconfirmed subscription and send a confirmation email."""
    email = email.strip().lower()

    if not email:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"submitted": False, "error": "Por favor ingresa un email."},
        )

    result = await session.execute(
        select(Subscription).where(Subscription.email == email)
    )
    existing: Subscription | None = result.scalar_one_or_none()

    if existing is not None and existing.confirmed:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "submitted": False,
                "error": "Ya tienes una cuenta con este email. "
                '<a href="/auth/login">Inicia sesion aqui</a>.',
            },
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
        "register.html",
        {"submitted": True, "error": None},
    )


# ── Confirm ───────────────────────────────────────────────────────────────────


@router.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse:
    """Confirm a subscription via the double opt-in link.

    Validates the confirmation token, sets confirmed=True, generates
    the unsubscribe_token, then redirects to /auth/magic-link/{token}.
    """
    result = await session.execute(
        select(Subscription).where(
            Subscription.confirmation_token == token  # type: ignore[arg-type]
        )
    )
    subscription: Subscription | None = result.scalar_one_or_none()

    if subscription is None or (
        subscription.token_expires_at is not None
        and subscription.token_expires_at < datetime.utcnow()
    ):
        return templates.TemplateResponse(
            request,
            "confirm_ok.html",
            {
                "success": False,
                "message": "El enlace de confirmacion no es valido o ha expirado. "
                "Vuelve a completar el formulario para recibir un nuevo enlace.",
            },
        )

    subscription.confirmed = True
    subscription.confirmation_token = None
    subscription.token_expires_at = None
    subscription.unsubscribe_token = uuid4()
    unsubscribe_token = subscription.unsubscribe_token
    await session.commit()

    return RedirectResponse(
        url=f"/auth/magic-link/{unsubscribe_token}",
        status_code=302,
    )


# ── Login ─────────────────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login form."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {"sent": False, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    session: DbSession,
    email: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Send a magic link with the unsubscribe token to the given email.

    Always returns the same message regardless of whether the email exists
    (prevents email enumeration).
    """
    email = email.strip().lower()

    if not email:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"sent": False, "error": "Por favor ingresa un email."},
        )

    result = await session.execute(
        select(Subscription).where(
            Subscription.email == email,
            Subscription.confirmed.is_(True),
        )
    )
    sub = result.scalar_one_or_none()

    if sub is not None and sub.unsubscribe_token is not None:
        try:
            await send_follow_link_email(email=str(sub.email), token=str(sub.unsubscribe_token))
        except NotificationError as exc:
            LOGGER.error("Failed to send login email to %s: %s", email, exc)

    return templates.TemplateResponse(
        request,
        "login.html",
        {"sent": True, "error": None},
    )


# ── Logout ────────────────────────────────────────────────────────────────────


@router.post("/logout")
async def logout(
    sub: Subscription = Depends(get_current_subscription),
) -> JSONResponse:
    """Close the current session.

    Logout is client-side: the caller removes the token from localStorage.
    The token remains valid server-side so previously-sent magic links
    continue to work. Server-side invalidation (token_invalidated_at)
    is reserved for future admin use.
    """
    return JSONResponse(content={"detail": "Sesion cerrada exitosamente."})


# ── Me ────────────────────────────────────────────────────────────────────────


@router.get("/me")
async def me(
    sub: Subscription | None = Depends(get_optional_subscription),
) -> JSONResponse:
    """Return the current user info if authenticated.

    Returns 401 if no valid token is provided.
    """
    if sub is None:
        raise HTTPException(status_code=401, detail="No autenticado.")
    return JSONResponse(
        content={
            "subscription_id": str(sub.id),
            "email": sub.email,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        }
    )


# ── Magic link landing ────────────────────────────────────────────────────────


@router.get("/magic-link/{token}", response_class=HTMLResponse)
async def magic_link_page(
    request: Request,
    token: str,
    session: DbSession,
) -> HTMLResponse:
    """Landing page after confirming or logging in.

    Saves the token to localStorage via JavaScript and redirects to /.
    """
    result = await session.execute(
        select(Subscription).where(
            Subscription.unsubscribe_token == token,  # type: ignore[arg-type]
            Subscription.confirmed.is_(True),
            Subscription.token_invalidated_at.is_(None),
        )
    )
    sub = result.scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "magic_link.html",
        {"valid": sub is not None, "token": token},
    )
