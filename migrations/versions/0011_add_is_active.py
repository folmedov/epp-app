"""Add is_active column to job_offers.

Revision ID: 0011_add_is_active
Revises: 0010_enable_unaccent
Create Date: 2026-04-07
"""

revision = "0011_add_is_active"
down_revision = "0010_enable_unaccent"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column(
        "job_offers",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_job_offers_is_active", "job_offers", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_job_offers_is_active", table_name="job_offers")
    op.drop_column("job_offers", "is_active")
