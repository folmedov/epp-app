"""Enable unaccent extension.

Revision ID: 0010_enable_unaccent
Revises: 0009_rename_enrichment_columns
Create Date: 2026-04-07
"""

revision = "0010_enable_unaccent"
down_revision = "0009_rename_enrichment_columns"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS unaccent")
