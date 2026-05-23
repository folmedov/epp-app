"""Add token_invalidated_at to subscriptions.

Stores when the unsubscribe_token was invalidated via logout.
Enables server-side token revocation.

Revision ID: 0015_add_token_invalidated_at
Revises: 0014_drop_keywords
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_add_token_invalidated_at"
down_revision = "0014_drop_keywords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("token_invalidated_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "token_invalidated_at")
