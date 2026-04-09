"""Async query functions for the web interface."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
import math
from sqlalchemy import desc, asc, case, or_
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import JobOffer


@dataclass
class OfferRow:
    """Lightweight read model for template rendering."""

    title: str
    institution: str
    region: str | None
    city: str | None
    gross_salary: Decimal | None
    state: str
    url: str | None
    start_date: Optional[object] = None
    close_date: Optional[object] = None


async def get_filter_options(session: AsyncSession) -> dict[str, list[str]]:
    """Return distinct non-null values for each filter dropdown."""
    result: dict[str, list[str]] = {}

    # Regions: alphabetical, but "Otras ubicaciones" always last.
    # Use a subquery to satisfy PostgreSQL's DISTINCT + ORDER BY constraint
    # (ORDER BY expressions must appear in the SELECT list with DISTINCT).
    _otras = "Otras ubicaciones"
    sort_key = case((JobOffer.region == _otras, 1), else_=0).label("_sort")
    subq = (
        select(JobOffer.region, sort_key)
        .where(JobOffer.region.isnot(None))
        .distinct()
        .subquery()
    )
    region_rows = await session.execute(
        select(subq.c.region).order_by(subq.c._sort, subq.c.region)
    )
    result["regions"] = [r[0] for r in region_rows]

    for col, key in (
        (JobOffer.institution, "institutions"),
        (JobOffer.state, "states"),
    ):
        rows = await session.execute(
            select(col).where(col.isnot(None)).distinct().order_by(col)
        )
        result[key] = [r[0] for r in rows]
    return result


async def get_offers(
    session: AsyncSession,
    *,
    region: Optional[str] = None,
    institution: Optional[str] = None,
    q: Optional[str] = None,
    states: list[str] | None = None,
    page: int = 1,
    per_page: int = 50,
    sort: Optional[str] = None,
    sort_dir: str = "desc",
    include_inactive: bool = False,
) -> tuple[list[OfferRow], bool, int, int]:
    """Query job offers with optional filters and simple page-based pagination.

    Returns a tuple `(offers, has_next)` where `has_next` indicates whether there
    may be more results after the returned page. Internally we request
    `per_page + 1` rows to determine `has_next`.
    """
    # Enforce sane bounds
    per_page = max(1, min(per_page, 500))
    page = max(1, page)

    stmt = select(
        JobOffer.title,
        JobOffer.institution,
        JobOffer.region,
        JobOffer.city,
        JobOffer.gross_salary,
        JobOffer.state,
        JobOffer.url,
        JobOffer.start_date,
        JobOffer.close_date,
    )

    # Sorting: allow ordering by a whitelist of columns
    ALLOWED_SORTS = {
        "title": JobOffer.title,
        "institution": JobOffer.institution,
        "region": JobOffer.region,
        "city": JobOffer.city,
        "salary": JobOffer.gross_salary,
        "state": JobOffer.state,
        "start_date": JobOffer.start_date,
        "close_date": JobOffer.close_date,
    }

    if sort and sort in ALLOWED_SORTS:
        col = ALLOWED_SORTS[sort]
        if (sort_dir or "").lower() == "asc":
            stmt = stmt.order_by(asc(col).nullslast(), desc(JobOffer.id))
        else:
            stmt = stmt.order_by(desc(col).nullslast(), desc(JobOffer.id))
    else:
        # Default: soonest-to-close first (NULLs last), then most-recently-started
        # for offers where close_date is unknown.
        stmt = stmt.order_by(
            asc(JobOffer.close_date).nullslast(),
            desc(JobOffer.start_date).nullslast(),
            desc(JobOffer.id),
        )

    if region:
        stmt = stmt.where(JobOffer.region == region)
    if institution:
        stmt = stmt.where(JobOffer.institution == institution)
    if q:
        # Case-insensitive substring match on title — use Postgres `unaccent()`
        # so searches ignore diacritics (e.g. 'analis' matches 'análisis').
        # NOTE: this requires the `unaccent` extension enabled in Postgres.
        stmt = stmt.where(func.unaccent(JobOffer.title).ilike(func.unaccent(f"%{q}%")))
    if states:
        stmt = stmt.where(JobOffer.state.in_(states))
    if not include_inactive:
        stmt = stmt.where(JobOffer.is_active.is_(True))
        stmt = stmt.where(
            or_(JobOffer.close_date.is_(None), JobOffer.close_date >= func.current_date())
        )

    # Count total matching rows for pager info
    count_stmt = select(func.count()).select_from(JobOffer)
    if region:
        count_stmt = count_stmt.where(JobOffer.region == region)
    if institution:
        count_stmt = count_stmt.where(JobOffer.institution == institution)
    if q:
        count_stmt = count_stmt.where(func.unaccent(JobOffer.title).ilike(func.unaccent(f"%{q}%")))
    if states:
        count_stmt = count_stmt.where(JobOffer.state.in_(states))
    if not include_inactive:
        count_stmt = count_stmt.where(JobOffer.is_active.is_(True))
        count_stmt = count_stmt.where(
            or_(JobOffer.close_date.is_(None), JobOffer.close_date >= func.current_date())
        )

    total = await session.scalar(count_stmt)
    total = int(total or 0)

    limit = per_page + 1
    offset = (page - 1) * per_page
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows = result.all()
    offers_all = [OfferRow(*row) for row in rows]
    has_next = len(offers_all) > per_page
    offers = offers_all[:per_page]

    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return offers, has_next, total, total_pages
