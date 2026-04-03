"""Backfill `job_offer_sources.job_offer_id` from `job_offers`.

Revision ID: 0002_backfill_job_offer_sources
Revises: 0001_initial
Create Date: 2026-04-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_backfill_job_offer_sources"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use a safe canonicalization: pick the most-recent job_offers row per
    # (source, external_id) using updated_at DESC, then link sources to that id.
    op.execute(
        """
        WITH canonical AS (
          SELECT id, source, external_id FROM (
            SELECT id, source, external_id,
                   ROW_NUMBER() OVER (PARTITION BY source, external_id ORDER BY updated_at DESC) as rn
            FROM job_offers
            WHERE external_id IS NOT NULL
          ) t WHERE rn = 1
        )
        UPDATE job_offer_sources s
        SET job_offer_id = c.id
        FROM canonical c
        WHERE s.job_offer_id IS NULL
          AND s.external_id IS NOT NULL
          AND s.source = c.source
          AND s.external_id = c.external_id;
        """
    )


def downgrade() -> None:
    # Best-effort: clear job_offer_id for rows that were set from job_offers
    op.execute(
        """
        UPDATE job_offer_sources s
        SET job_offer_id = NULL
        FROM job_offers j
        WHERE s.job_offer_id = j.id
          AND j.external_id IS NOT NULL;
        """
    )
