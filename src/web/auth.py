"""Auth dependencies for Bearer token authentication.

Provides two dependencies for route handlers:
  - get_optional_subscription: returns Subscription or None (no error raised)
  - get_current_subscription: returns Subscription or raises 401

The token is read from:
  1. Authorization: Bearer <uuid> header (primary, for fetch/XHR calls)
  2. ?token=<uuid> query param (fallback, for HTMX partial loads)

On logout, token_invalidated_at is set on the subscription row and the
token is no longer accepted by either method.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Subscription
from src.web.deps import get_db_session

LOGGER = logging.getLogger(__name__)


async def _lookup_subscription(
    session: AsyncSession,
    raw_token: str,
) -> Subscription | None:
    """Validate a token string and return the subscription, or None.

    Checks:
      - token is a valid UUID
      - matching confirmed subscription exists
      - token_invalidated_at is NULL (not logged out)
    """
    if not raw_token:
        return None
    try:
        UUID(raw_token)
    except ValueError:
        return None
    result = await session.execute(
        select(Subscription).where(
            Subscription.unsubscribe_token == raw_token,  # type: ignore[arg-type]
            Subscription.confirmed.is_(True),
            Subscription.token_invalidated_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_optional_subscription(
    session: AsyncSession = Depends(get_db_session),
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
    token: Annotated[str | None, Query()] = None,
) -> Subscription | None:
    """Extract and validate auth token from headers or query params.

    Returns the subscription if valid, None otherwise. Never raises.
    """
    raw: str | None = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization[7:]
    elif token:
        raw = token

    return await _lookup_subscription(session, raw) if raw else None


async def get_current_subscription(
    sub: Subscription | None = Depends(get_optional_subscription),
) -> Subscription:
    """Require a valid authenticated subscription.

    Raises HTTP 401 if no valid token is provided.
    """
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Proporciona un token válido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return sub
