"""One-time migration: normalise the ``region`` column in ``job_offers``.

Two passes are executed in sequence:

Pass 1 — re-normalise values currently stored in ``job_offers.region``
  (handles canonical names, "Otras ubicaciones" sentinel, and NULLs).

Pass 2 — recover records whose region is NULL or incorrectly set to
  "Otras ubicaciones" by re-reading the original raw data from
  ``job_offer_sources`` and re-normalizing it.  This corrects entries
  that were misclassified in a previous run (e.g. "Arica y Parinacota"
  incorrectly classified as multi-region).

Usage::

    PYTHONPATH=. python scripts/normalize_regions.py --dry-run
    PYTHONPATH=. python scripts/normalize_regions.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import text

from src.core.regions import normalize_region_from_code, normalize_region_from_text, OTRAS_UBICACIONES
from src.database.session import SessionFactory, engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_EXTRACT_REGION_SQL = text("""
    SELECT
        jo.id,
        jo.region AS current_region,
        jos.source,
        jos.raw_data
    FROM job_offers jo
    JOIN job_offer_sources jos ON jos.job_offer_id = jo.id
    WHERE jo.region IS NULL OR jo.region = :otras
    ORDER BY jo.id
""")



def _region_from_raw(source: str, raw_data: dict) -> str | None:
    """Re-derive a canonical region name from the original raw API payload."""
    if source == "TEEE":
        code = raw_data.get("Codigo Region")
        raw_text = raw_data.get("Region")
        return normalize_region_from_code(code) or normalize_region_from_text(raw_text)
    if source == "EEPP":
        return normalize_region_from_text(raw_data.get("Región"))
    return None


async def run(*, dry_run: bool) -> None:
    async with SessionFactory() as session:
        # ── Pass 1: normalize values already in region column ────────────
        rows = await session.execute(
            text("SELECT DISTINCT region FROM job_offers WHERE region IS NOT NULL ORDER BY region")
        )
        distinct: list[str] = [r[0] for r in rows]
        log.info("Pass 1 — %d distinct region values in the database.", len(distinct))

        pass1_updated = 0
        for raw in distinct:
            canonical = normalize_region_from_text(raw)
            if canonical == raw:
                continue
            # Unrecognised values become NULL (genuinely unknown, no raw_data fallback)
            new_val: str | None = canonical  # None if still unrecognised
            action = f"→ {canonical!r}" if canonical else "→ NULL (unrecognised)"
            result = await session.execute(
                text("UPDATE job_offers SET region = :new WHERE region = :old"),
                {"new": new_val, "old": raw},
            )
            count = result.rowcount
            pass1_updated += count
            log.info("  %r %s  (%d row%s)", raw, action, count, "s" if count != 1 else "")

        log.info("Pass 1 complete: %d rows updated.", pass1_updated)

        # ── Pass 2: recover NULL / misclassified "Otras ubicaciones" ─────
        # Fetch all affected records at once, compute new values in Python,
        # then issue one UPDATE per distinct target value (bulk by id list).
        recover_rows = await session.execute(_EXTRACT_REGION_SQL, {"otras": OTRAS_UBICACIONES})
        records = recover_rows.all()
        log.info("Pass 2 — %d records with NULL or 'Otras ubicaciones' to re-evaluate from raw_data.", len(records))

        # Group offer ids by the recovered region value
        from collections import defaultdict
        groups: dict[str | None, list[int]] = defaultdict(list)
        corrected_ids: list[int] = []

        for offer_id, current_region, source, raw_data in records:
            recovered = _region_from_raw(source, raw_data)
            if recovered == current_region:
                continue
            groups[recovered].append(offer_id)
            if current_region == OTRAS_UBICACIONES and recovered not in (None, OTRAS_UBICACIONES):
                corrected_ids.append(offer_id)

        pass2_updated = 0
        pass2_corrected = len(corrected_ids)
        for new_region, ids in groups.items():
            result = await session.execute(
                text("UPDATE job_offers SET region = :region WHERE id = ANY(:ids)"),
                {"region": new_region, "ids": ids},
            )
            count = result.rowcount
            pass2_updated += count
            label = repr(new_region) if new_region is not None else "NULL"
            log.info("  → %-35s  (%d row%s)", label, count, "s" if count != 1 else "")

        log.info(
            "Pass 2 complete: %d rows updated (%d corrected from 'Otras ubicaciones').",
            pass2_updated, pass2_corrected,
        )

        total = pass1_updated + pass2_updated
        if dry_run:
            await session.rollback()
            log.info("Dry-run: rolled back all changes (%d total rows would have been updated).", total)
        else:
            await session.commit()
            log.info("Done. %d total rows updated.", total)

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalise region values in job_offers.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without committing them.")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
