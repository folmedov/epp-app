"""Offer follows table for per-offer state-change subscriptions.

Revision ID: 0013_offer_follows
Revises: 0012_notifications_schema
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0013_offer_follows"
down_revision = "0012_notifications_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_follows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "job_offer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_offers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("last_state", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("subscription_id", "job_offer_id", name="uq_offer_follows"),
    )


def downgrade() -> None:
    op.drop_table("offer_follows")
