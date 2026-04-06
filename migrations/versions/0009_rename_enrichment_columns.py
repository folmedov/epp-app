"""Rename enrichment columns from Spanish to English.

salary_bruto    → gross_salary
primer_empleo   → first_employment
vacantes        → vacancies
priorizado      → prioritized

Revision ID: 0009_rename_enrichment_columns
Revises: 0008_add_eepp_enrichment_columns
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op

revision = "0009_rename_enrichment_columns"
down_revision = "0008_add_eepp_enrichment_columns"
branch_labels = None
depends_on = None

_RENAMES = [
    ("salary_bruto", "gross_salary"),
    ("primer_empleo", "first_employment"),
    ("vacantes", "vacancies"),
    ("priorizado", "prioritized"),
]


def upgrade() -> None:
    for old, new in _RENAMES:
        op.alter_column("job_offers", old, new_column_name=new)


def downgrade() -> None:
    for old, new in _RENAMES:
        op.alter_column("job_offers", new, new_column_name=old)
