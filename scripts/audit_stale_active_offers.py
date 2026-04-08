"""Audit script: find active offers with a past close_date and cross-check with TEEE.

Usage:
    python scripts/audit_stale_active_offers.py [--sample N] [--no-teee]

Options:
    --sample N    How many stale offers to look up in TEEE (default: 20).
    --no-teee     Skip the live TEEE lookup; only print the DB report.

The script:
  1. Queries the DB for job_offers in state 'postulacion' or 'evaluacion'
     whose close_date is earlier than today (UTC).
  2. Prints a summary table of those offers.
  3. Takes a random sample and queries TEEE live to fetch the current state
     for offers that can be matched by their external_id (from job_offer_sources).
  4. Prints a diff showing DB state vs TEEE current state.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# ── project imports ──────────────────────────────────────────────────────────
sys.path.insert(0, ".")
from src.database.session import get_session
from src.database.models import JobOffer, JobOfferSource
from src.ingestion.teee_client import TEEEClient

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(message)s",
)
LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DB query
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StaleOffer:
    id: UUID
    title: str
    institution: str
    state: str
    close_date: datetime
    start_date: Optional[datetime]
    region: Optional[str]
    url: Optional[str]
    source: str
    days_overdue: int


async def fetch_stale_active(session: AsyncSession) -> list[StaleOffer]:
    """Return active offers whose close_date is in the past."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # DB stores naive datetimes
    stmt = (
        select(
            JobOffer.id,
            JobOffer.title,
            JobOffer.institution,
            JobOffer.state,
            JobOffer.close_date,
            JobOffer.start_date,
            JobOffer.region,
            JobOffer.url,
            JobOffer.source,
        )
        .where(JobOffer.state.in_(["postulacion", "evaluacion"]))
        .where(JobOffer.close_date.isnot(None))
        .where(JobOffer.close_date < now)
        .order_by(JobOffer.close_date.asc())
    )
    rows = (await session.execute(stmt)).all()
    result = []
    for r in rows:
        delta = (now - r.close_date.replace(tzinfo=None)).days if r.close_date else 0
        result.append(
            StaleOffer(
                id=r.id,
                title=r.title,
                institution=r.institution,
                state=r.state,
                close_date=r.close_date,
                start_date=r.start_date,
                region=r.region,
                url=r.url,
                source=r.source,
                days_overdue=delta,
            )
        )
    return result


async def fetch_external_ids(session: AsyncSession, offer_ids: list[UUID]) -> dict[UUID, list[tuple[str, str]]]:
    """Return {offer_id: [(source, external_id), ...]} for the given offer IDs."""
    if not offer_ids:
        return {}
    stmt = (
        select(
            JobOfferSource.job_offer_id,
            JobOfferSource.source,
            JobOfferSource.external_id,
        )
        .where(JobOfferSource.job_offer_id.in_(offer_ids))
        .where(JobOfferSource.external_id.isnot(None))
    )
    rows = (await session.execute(stmt)).all()
    result: dict[UUID, list[tuple[str, str]]] = {}
    for r in rows:
        result.setdefault(r.job_offer_id, []).append((r.source, r.external_id))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TEEE lookup
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_teee_index() -> dict[str, dict[str, Any]]:
    """Fetch all active TEEE offers (postulacion + evaluacion) and index by external_id."""
    client = TEEEClient()
    LOGGER.info("Fetching TEEE postulacion…")
    postulacion = await client.fetch_postulacion()
    LOGGER.info("  → %d offers", len(postulacion))
    LOGGER.info("Fetching TEEE evaluacion…")
    evaluacion = await client.fetch_evaluacion()
    LOGGER.info("  → %d offers", len(evaluacion))
    LOGGER.info("Fetching TEEE finalizado (sample check)…")
    finalizado = await client.fetch_finalizado()
    LOGGER.info("  → %d offers", len(finalizado))

    index: dict[str, dict[str, Any]] = {}
    for offer in [*postulacion, *evaluacion, *finalizado]:
        eid = offer.get("external_id")
        if eid and not str(eid).startswith("teee:_id:"):
            index[str(eid)] = offer
    LOGGER.info("TEEE index built: %d entries with a stable external_id", len(index))
    return index


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d/%m/%Y")


def print_stale_report(stale: list[StaleOffer]) -> None:
    print("\n" + "=" * 90)
    print(f"  OFERTAS ACTIVAS CON FECHA DE CIERRE VENCIDA  (encontradas: {len(stale)})")
    print("=" * 90)

    # Group by state
    by_state: dict[str, list[StaleOffer]] = {}
    for o in stale:
        by_state.setdefault(o.state, []).append(o)

    for state, offers in sorted(by_state.items()):
        print(f"\n  Estado: {state.upper()}  ({len(offers)} ofertas)")
        print(f"  {'Cierre':>10}  {'Días':>5}  {'Fuente':6}  Institución / Cargo")
        print("  " + "-" * 80)
        for o in offers:
            inst = o.institution[:35].ljust(35)
            title = o.title[:38]
            print(f"  {_fmt(o.close_date):>10}  {o.days_overdue:>5}d  {o.source:6}  {inst}  {title}")

    # Distribution by days overdue
    buckets = {"≤7d": 0, "8–30d": 0, "31–90d": 0, ">90d": 0}
    for o in stale:
        d = o.days_overdue
        if d <= 7:
            buckets["≤7d"] += 1
        elif d <= 30:
            buckets["8–30d"] += 1
        elif d <= 90:
            buckets["31–90d"] += 1
        else:
            buckets[">90d"] += 1

    print(f"\n  Distribución por días de atraso:")
    for label, count in buckets.items():
        bar = "█" * count
        print(f"    {label:>6}  {count:>4}  {bar}")
    print()


def print_teee_diff(sample: list[StaleOffer], ext_ids: dict[UUID, list[tuple[str, str]]], teee_index: dict[str, dict[str, Any]]) -> None:
    print("\n" + "=" * 90)
    print(f"  COTEJO CON TEEE  (muestra: {len(sample)} ofertas)")
    print("=" * 90)

    found_changed = 0
    found_same = 0
    not_found = 0

    for o in sample:
        sources = ext_ids.get(o.id, [])
        teee_eids = [eid for src, eid in sources if src == "TEEE" and not eid.startswith("teee:_id:")]

        teee_hit: Optional[dict[str, Any]] = None
        matched_eid: Optional[str] = None
        for eid in teee_eids:
            if eid in teee_index:
                teee_hit = teee_index[eid]
                matched_eid = eid
                break

        title_short = o.title[:55]
        print(f"\n  [{o.state.upper()}] {title_short}")
        print(f"    Institución : {o.institution[:60]}")
        print(f"    Cierre BD   : {_fmt(o.close_date)}  ({o.days_overdue}d vencido)")
        print(f"    Fuente      : {o.source}")
        if o.url:
            print(f"    URL         : {o.url}")

        if teee_eids:
            print(f"    external_id : {', '.join(teee_eids)}")
        else:
            print(f"    external_id : (no TEEE id)")

        if teee_hit:
            teee_state = teee_hit.get("state", "?")
            teee_close = teee_hit.get("close_date")
            teee_close_str = _fmt(teee_close) if teee_close else "—"
            if teee_state != o.state:
                print(f"    ✦ TEEE estado ACTUAL : {teee_state.upper()}  (BD tiene: {o.state})")
                found_changed += 1
            else:
                print(f"    ✓ TEEE estado        : {teee_state} (igual a BD)")
                found_same += 1
            print(f"    ✦ TEEE fecha cierre  : {teee_close_str}")
        else:
            if teee_eids:
                print(f"    ✗ No encontrada en TEEE activo/finalizado → posiblemente eliminada del índice")
            else:
                print(f"    ✗ Sin external_id TEEE → imposible cotejar directamente")
            not_found += 1

    print(f"\n  Resumen cotejo:")
    print(f"    Estado cambiado en TEEE : {found_changed}")
    print(f"    Estado igual en TEEE    : {found_same}")
    print(f"    No encontradas en TEEE  : {not_found}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main(sample_size: int, skip_teee: bool) -> None:
    async with get_session() as session:
        LOGGER.info("Consultando BD…")
        stale = await fetch_stale_active(session)

        if not stale:
            print("\nNo hay ofertas activas con fecha de cierre vencida. Todo OK.")
            return

        print_stale_report(stale)

        if skip_teee:
            return

        # Determine sample — prioritize TEEE-sourced or enriched offers
        teee_offers = [o for o in stale if o.source == "TEEE"]
        other_offers = [o for o in stale if o.source != "TEEE"]
        pool = teee_offers + other_offers
        sample = pool[:sample_size] if len(pool) <= sample_size else random.sample(pool, sample_size)
        # For meaningful TEEE lookup prefer offers closer to today
        sample.sort(key=lambda o: o.close_date, reverse=True)

        LOGGER.info("Cargando external_ids de la muestra desde BD…")
        ext_ids = await fetch_external_ids(session, [o.id for o in sample])

    LOGGER.info("Consultando TEEE en vivo…")
    teee_index = await fetch_teee_index()

    print_teee_diff(sample, ext_ids, teee_index)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit stale active offers vs TEEE")
    parser.add_argument("--sample", type=int, default=20, help="Offers to cross-check with TEEE (default: 20)")
    parser.add_argument("--no-teee", action="store_true", help="Skip live TEEE lookup")
    args = parser.parse_args()

    asyncio.run(main(sample_size=args.sample, skip_teee=args.no_teee))
