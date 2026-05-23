"""Create search_subscriptions table for per-term search matching.

Revision ID: 0016_add_search_subscriptions
Revises: 0015_add_token_invalidated_at
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_add_search_subscriptions"
down_revision = "0015_add_token_invalidated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subscription_id", "term", name="uq_search_subscriptions"),
    )
    op.create_index(
        "ix_search_subscriptions_subscription_id",
        "search_subscriptions",
        ["subscription_id"],
    )


def downgrade() -> None:
    op.drop_table("search_subscriptions")
