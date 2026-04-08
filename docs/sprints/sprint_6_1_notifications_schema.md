# Sprint 6.1 — Notifications DB Schema

## Context

The notification system requires three schema changes:

1. A `subscriptions` table to store subscriber preferences and opt-in state.
2. A `notification_queue` table as an idempotent work queue for email sends.
3. A `notified_at` column on `job_offers` to mark which offers have already been processed for immediate notifications.

No external broker (Redis, RabbitMQ) is needed — the Postgres queue is sufficient given the expected volume and the sequential nature of the cron-based pipeline.

## Design

### Table: `subscriptions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | VARCHAR(254) | Unique; lowercased on insert |
| `keywords` | TEXT[] | e.g. `["analis", "informatic"]`; OR match against offer title |
| `confirmed` | BOOLEAN | DEFAULT FALSE; double opt-in |
| `confirmation_token` | UUID | Single-use; 24h expiry |
| `token_expires_at` | TIMESTAMP (no tz) | |
| `unsubscribe_token` | UUID | Permanent; generated on confirmation |
| `created_at` | TIMESTAMP (no tz) | |

- `email` is the public identifier. One row per subscriber.
- Keywords are stored as-is (lowercase stems); matching uses `unaccent ILIKE '%keyword%'`.
- Unconfirmed rows with `token_expires_at < NOW()` are periodically purged by `scripts/cleanup_subscriptions.py`.

### Table: `notification_queue`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `subscription_id` | UUID FK → subscriptions | ON DELETE CASCADE |
| `job_offer_id` | UUID FK → job_offers | ON DELETE CASCADE |
| `notification_type` | VARCHAR(16) | `immediate` \| `digest` |
| `status` | VARCHAR(16) | `pending` \| `sent` \| `failed` |
| `attempts` | SMALLINT | DEFAULT 0 |
| `created_at` | TIMESTAMP (no tz) | |
| `sent_at` | TIMESTAMP (no tz) | Nullable |

- Unique constraint on `(subscription_id, job_offer_id, notification_type)` to prevent duplicate queue entries.
- `status='failed'` rows with `attempts >= 3` are not retried automatically (manual review).
- ON DELETE CASCADE on both FKs: deleting a subscription cleans up its queue entries automatically.

### Column: `job_offers.notified_at`

| Property | Value |
|---|---|
| Type | `TIMESTAMP (no tz)` nullable |
| Default | NULL |
| Managed by | `scripts/notify_new_offers.py` |

Set to `NOW()` after all confirmed subscriptions have been checked against a new offer, regardless of whether any match was found. Offers with `notified_at IS NULL` are the candidates for immediate notifications.

## Implementation

### Migration `0012_notifications_schema`

```sql
-- subscriptions
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(254) NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    confirmation_token UUID,
    token_expires_at TIMESTAMP,
    unsubscribe_token UUID,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX ix_subscriptions_email ON subscriptions (email);

-- notification_queue
CREATE TABLE notification_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    job_offer_id UUID NOT NULL REFERENCES job_offers(id) ON DELETE CASCADE,
    notification_type VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMP
);
CREATE UNIQUE INDEX ix_notification_queue_dedup
    ON notification_queue (subscription_id, job_offer_id, notification_type);
CREATE INDEX ix_notification_queue_status ON notification_queue (status);

-- job_offers.notified_at
ALTER TABLE job_offers ADD COLUMN notified_at TIMESTAMP NULL;
```

### `src/database/models.py`

Three additions:

```python
# On JobOffer:
notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

# New model:
class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, server_default="{}")
    confirmed: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    confirmation_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    unsubscribe_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

# New model:
class NotificationQueue(Base):
    __tablename__ = "notification_queue"
    __table_args__ = (
        UniqueConstraint("subscription_id", "job_offer_id", "notification_type", name="uq_notification_queue_dedup"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    subscription_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    job_offer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger(), nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
```

## Acceptance criteria

- [ ] `alembic upgrade head` applies migration `0012` cleanly against an existing DB.
- [ ] `alembic downgrade -1` removes all three changes without errors.
- [ ] `subscriptions` unique index on `email` prevents duplicate rows.
- [ ] `notification_queue` unique constraint on `(subscription_id, job_offer_id, notification_type)` prevents duplicate queue entries.
- [ ] Deleting a `subscription` row cascades to its `notification_queue` rows.
- [ ] `job_offers.notified_at` is NULL for all existing rows after migration.
