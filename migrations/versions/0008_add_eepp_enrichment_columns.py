"""Add EEPP-exclusive enrichment columns to job_offers.

These columns are populated exclusively from EEPP offer payloads and are
used to enrich canonical rows that were originally ingested from TEEE.

New columns:
  primer_empleo  BOOLEAN nullable — whether the position qualifies as first
                 employment (``esPrimerEmpleo`` in EEPP payload).
  vacantes       SMALLINT nullable — number of open positions
                 (``Nº de Vacantes`` in EEPP payload).
  priorizado     BOOLEAN nullable — whether the offer is flagged as priority
                 (``Priorizado`` in EEPP payload).

Revision ID: 0008_add_eepp_enrichment_columns
Revises: 0007_fix_job_offer_sources_unique
Create Date: 2026-04-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_eepp_enrichment_columns"
down_revision = "0007_fix_jos_unique_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_offers", sa.Column("primer_empleo", sa.Boolean(), nullable=True))
    op.add_column("job_offers", sa.Column("vacantes", sa.SmallInteger(), nullable=True))
    op.add_column("job_offers", sa.Column("priorizado", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_offers", "priorizado")
    op.drop_column("job_offers", "vacantes")
    op.drop_column("job_offers", "primer_empleo")
