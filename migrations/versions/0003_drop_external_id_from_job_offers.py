"""Drop `external_id` column from `job_offers`.

Revision ID: 0003_drop_external_id
Revises: 0002_backfill_job_offer_sources
Create Date: 2026-04-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_drop_external_id"
down_revision = "0002_backfill_job_offer_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the external_id column from job_offers now that sources are linked.
    with op.batch_alter_table("job_offers") as batch_op:
        batch_op.drop_column("external_id")


def downgrade() -> None:
    # Recreate the column (nullable) and attempt a best-effort refill from sources.
    with op.batch_alter_table("job_offers") as batch_op:
        batch_op.add_column(sa.Column("external_id", sa.String(length=255), nullable=True))

    op.execute(
        """
        UPDATE job_offers j
        SET external_id = s.external_id
        FROM job_offer_sources s
        WHERE s.job_offer_id = j.id
          AND j.external_id IS NULL;
        """
    )
