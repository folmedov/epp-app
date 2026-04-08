"""Notifications schema: subscriptions, notification_queue, job_offers.notified_at.

Revision ID: 0012_notifications_schema
Revises: 0011_add_is_active
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012_notifications_schema"
down_revision = "0011_add_is_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── subscriptions ────────────────────────────────────────────────────────
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("keywords", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confirmation_token", UUID(as_uuid=True), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("unsubscribe_token", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_subscriptions_email", "subscriptions", ["email"], unique=True)

    # ── notification_queue ────────────────────────────────────────────────────
    op.create_table(
        "notification_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_offer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notification_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("sent_at", sa.DateTime(timezone=False), nullable=True),
        sa.UniqueConstraint(
            "subscription_id", "job_offer_id", "notification_type",
            name="uq_notification_queue_dedup",
        ),
    )
    op.create_index("ix_notification_queue_status", "notification_queue", ["status"])

    # ── job_offers.notified_at ────────────────────────────────────────────────
    op.add_column(
        "job_offers",
        sa.Column("notified_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_offers", "notified_at")
    op.drop_index("ix_notification_queue_status", table_name="notification_queue")
    op.drop_table("notification_queue")
    op.drop_index("ix_subscriptions_email", table_name="subscriptions")
    op.drop_table("subscriptions")
