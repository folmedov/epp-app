"""Route handlers for job offers listing and filtering."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def offers_page(request: Request) -> HTMLResponse:
    """Full page render of the offers list."""
    return templates.TemplateResponse(
        request,
        "offers.html",
        {"offers": [], "regions": [], "cities": [], "institutions": []},
    )
