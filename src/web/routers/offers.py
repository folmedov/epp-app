"""Route handlers for job offers listing and filtering."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.web.deps import get_db_session
from src.web.queries import get_filter_options, get_offers
from src.web.templating import templates

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/", response_class=HTMLResponse)
async def offers_page(
    request: Request,
    session: DbSession,
    region: Optional[str] = None,
    city: Optional[str] = None,
    institution: Optional[str] = None,
    q: Optional[str] = None,
    state: list[str] = Query(default=[]),
    page: int = 1,
    per_page: int = 50,
    sort: Optional[str] = None,
    sort_dir: str = "asc",
) -> HTMLResponse:
    """Full page render of the offers list with filter dropdowns."""
    filter_opts = await get_filter_options(session)
    offers, has_next, total, total_pages = await get_offers(
        session,
        region=region or None,
        city=city or None,
        institution=institution or None,
        q=q or None,
        states=state or None,
        page=page,
        per_page=per_page,
        sort=sort,
        sort_dir=sort_dir,
    )
    return templates.TemplateResponse(
        request,
        "offers.html",
        {
            "offers": offers,
            "q": q,
            "page": page,
            "per_page": per_page,
            "has_next": has_next,
            "total": total,
            "total_pages": total_pages,
            "sort": sort,
            "sort_dir": sort_dir,
            "selected_states": state,
            **filter_opts,
        },
    )


@router.get("/offers/partial", response_class=HTMLResponse)
async def offers_partial(
    request: Request,
    session: DbSession,
    region: Optional[str] = None,
    city: Optional[str] = None,
    institution: Optional[str] = None,
    q: Optional[str] = None,
    state: list[str] = Query(default=[]),
    page: int = 1,
    per_page: int = 50,
    sort: Optional[str] = None,
    sort_dir: str = "asc",
) -> HTMLResponse:
    """HTMX partial: returns only the table rows matching the given filters.

    When accessed directly (no HX-Request header), redirects to the full page
    at / preserving all query parameters so styles are not lost.
    """
    if not request.headers.get("HX-Request"):
        qs = str(request.url.query)
        return RedirectResponse(url=f"/?{qs}" if qs else "/", status_code=302)
    offers, has_next, total, total_pages = await get_offers(
        session,
        region=region or None,
        city=city or None,
        institution=institution or None,
        q=q or None,
        states=state or None,
        page=page,
        per_page=per_page,
        sort=sort,
        sort_dir=sort_dir,
    )
    return templates.TemplateResponse(
        request,
        "partials/offers_table.html",
        {
            "offers": offers,
            "q": q,
            "page": page,
            "per_page": per_page,
            "has_next": has_next,
            "total": total,
            "total_pages": total_pages,
            "sort": sort,
            "sort_dir": sort_dir,
        },
    )
