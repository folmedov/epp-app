"""Add cross_source_key column to job_offers.

cross_source_key is a source-agnostic MD5 linking key computed as
MD5("cross|{external_id}") for offers with a verified external_id.
It enables the upsert flow to detect that EEPP and TEEE ingestions
of the same offer (same external_id) should share one canonical row
rather than creating two separate ones.

Revision ID: 0006_add_cross_source_key
Revises: 0005_dates_as_datetime
Create Date: 2026-04-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_add_cross_source_key"
down_revision = "0005_dates_as_datetime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_offers",
        sa.Column("cross_source_key", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_job_offers_cross_source_key",
        "job_offers",
        ["cross_source_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_offers_cross_source_key", table_name="job_offers")
    op.drop_column("job_offers", "cross_source_key")
