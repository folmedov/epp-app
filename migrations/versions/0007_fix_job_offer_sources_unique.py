"""Replace UNIQUE(source, external_id) with UNIQUE(job_offer_id, source) on job_offer_sources.

With the domain-scoped fingerprint introduced in Sprint 3.12, the same TEEE
``ID Conv`` value can legitimately map to two distinct canonical job_offer rows
when those offers come from different portals (e.g. junji.myfront.cl and
empleospublicos.cl both reporting ``ID Conv=18271``).

The old ``UNIQUE(source, external_id)`` constraint prevented a second source
row from being created, leaving one of the two job_offer rows orphaned (no
matching job_offer_sources row).

The semantically correct constraint is ``UNIQUE(job_offer_id, source)``:
"this source contributed to this canonical job offer".  It remains idempotent
across re-runs and allows the same external_id to appear in multiple source
rows when those rows belong to different canonical job_offer rows.

Revision ID: 0007_fix_job_offer_sources_unique
Revises: 0006_add_cross_source_key
Create Date: 2026-04-06 00:00:00.000000
"""

from alembic import op

revision = "0007_fix_jos_unique_constraint"
down_revision = "0006_add_cross_source_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate (job_offer_id, source) rows before adding the new constraint.
    # Duplicates exist for Stage-B offers (external_id generated from elastic _id)
    # that appeared in multiple state batches within --initial loads: each batch
    # produced a separate source row with a different generated external_id but the
    # same job_offer_id.  Keep only the most-recently ingested row per pair.
    op.execute("""
        DELETE FROM job_offer_sources
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_offer_id, source
                           ORDER BY ingested_at DESC
                       ) AS rn
                FROM job_offer_sources
                WHERE job_offer_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
    """)

    op.drop_constraint(
        "uq_job_offer_sources_source_external_id",
        "job_offer_sources",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_job_offer_sources_job_offer_id_source",
        "job_offer_sources",
        ["job_offer_id", "source"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_job_offer_sources_job_offer_id_source",
        "job_offer_sources",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_job_offer_sources_source_external_id",
        "job_offer_sources",
        ["source", "external_id"],
    )
