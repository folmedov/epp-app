"""Add ministry, start_date, close_date and conv_type to job_offers.

Revision ID: 0004_add_ministry_dates_conv_type
Revises: 0003_drop_external_id
Create Date: 2026-04-03 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_add_ministry_dates"
down_revision = "0003_drop_external_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_offers") as batch_op:
        batch_op.add_column(sa.Column("ministry", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("start_date", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("close_date", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("conv_type", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_offers") as batch_op:
        batch_op.drop_column("conv_type")
        batch_op.drop_column("close_date")
        batch_op.drop_column("start_date")
        batch_op.drop_column("ministry")
