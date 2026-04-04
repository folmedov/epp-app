"""Convert start_date and close_date from VARCHAR to TIMESTAMP.

TEEE delivers dates as 'DD/MM/YYYY HH:MI' or 'DD/MM/YYYY HH:MI:SS'.
The migration converts both variants using a CASE / TO_TIMESTAMP expression.

Revision ID: 0005_dates_as_datetime
Revises: 0004_add_ministry_dates
Create Date: 2026-04-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_dates_as_datetime"
down_revision = "0004_add_ministry_dates"
branch_labels = None
depends_on = None

_USING = """
    CASE
        WHEN {col} IS NULL THEN NULL
        WHEN {col} ~ E'^\\\\d{{2}}/\\\\d{{2}}/\\\\d{{4}} \\\\d+:\\\\d{{2}}:\\\\d{{2}}$'
            THEN TO_TIMESTAMP({col}, 'DD/MM/YYYY HH24:MI:SS')
        WHEN {col} ~ E'^\\\\d{{2}}/\\\\d{{2}}/\\\\d{{4}} \\\\d+:\\\\d{{2}}$'
            THEN TO_TIMESTAMP({col}, 'DD/MM/YYYY HH24:MI')
        ELSE NULL
    END
"""


def upgrade() -> None:
    op.alter_column(
        "job_offers",
        "start_date",
        existing_type=sa.String(length=64),
        type_=sa.DateTime(),
        nullable=True,
        postgresql_using=_USING.format(col="start_date"),
    )
    op.alter_column(
        "job_offers",
        "close_date",
        existing_type=sa.String(length=64),
        type_=sa.DateTime(),
        nullable=True,
        postgresql_using=_USING.format(col="close_date"),
    )


def downgrade() -> None:
    op.alter_column(
        "job_offers",
        "start_date",
        existing_type=sa.DateTime(),
        type_=sa.String(length=64),
        nullable=True,
        postgresql_using="TO_CHAR(start_date, 'DD/MM/YYYY HH24:MI:SS')",
    )
    op.alter_column(
        "job_offers",
        "close_date",
        existing_type=sa.DateTime(),
        type_=sa.String(length=64),
        nullable=True,
        postgresql_using="TO_CHAR(close_date, 'DD/MM/YYYY HH24:MI:SS')",
    )
