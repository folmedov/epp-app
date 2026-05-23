"""Drop keywords and notified_at; cleanup notification_queue.

Removes the keyword-matching notification system that is being replaced
by per-offer following with state-change notifications.

Changes:
  - Drop `keywords` column from `subscriptions`
  - Drop `notified_at` column from `job_offers`
  - Delete all rows from `notification_queue` (they were keyword-driven)

Revision ID: 0014_drop_keywords
Revises: 0013_offer_follows
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_drop_keywords"
down_revision = "0013_offer_follows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clean up notification_queue rows (keyword-driven)
    op.execute("DELETE FROM notification_queue")

    # Drop columns
    op.drop_column("subscriptions", "keywords")
    op.drop_column("job_offers", "notified_at")


def downgrade() -> None:
    # Restore notified_at
    op.add_column(
        "job_offers",
        sa.Column("notified_at", sa.DateTime(timezone=False), nullable=True),
    )

    # Restore keywords (empty array default)
    op.add_column(
        "subscriptions",
        sa.Column(
            "keywords",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
