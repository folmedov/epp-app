"""SQLAlchemy 2.0 models for job offer persistence.

The models in this module define the first canonical database contract used by
the ETL pipeline. They are intentionally aligned with the V1 data model from
the architecture and sprint documentation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, Integer, Numeric, String, SmallInteger, Text, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
	"""Base class for async SQLAlchemy ORM models."""


class JobOffer(Base):
	"""ORM model for the canonical job offers table."""

	__tablename__ = "job_offers"

	id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		primary_key=True,
		default=uuid4,
	)
	fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
	source: Mapped[str] = mapped_column(String(32), nullable=False)
	title: Mapped[str] = mapped_column(String(512), nullable=False)
	institution: Mapped[str] = mapped_column(String(512), nullable=False)
	gross_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
	state: Mapped[str] = mapped_column(String(32), nullable=False)
	region: Mapped[str | None] = mapped_column(String(255), nullable=True)
	city: Mapped[str | None] = mapped_column(String(255), nullable=True)
	url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
	ministry: Mapped[str | None] = mapped_column(String(255), nullable=True)
	start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
	close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
	conv_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
	cross_source_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
	first_employment: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
	vacancies: Mapped[int | None] = mapped_column(SmallInteger(), nullable=True)
	prioritized: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		server_default=func.now(),
		nullable=False,
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		server_default=func.now(),
		onupdate=func.now(),
		nullable=False,
	)
	is_active: Mapped[bool] = mapped_column(
		Boolean(), nullable=False, default=True, server_default="true", index=True
	)
	notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class JobOfferSource(Base):
	"""Per-source ingest records with raw payload and metadata."""

	__tablename__ = "job_offer_sources"

	id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		primary_key=True,
		default=uuid4,
	)
	job_offer_id: Mapped[UUID | None] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("job_offers.id"),
		nullable=True,
		index=True,
	)
	source: Mapped[str] = mapped_column(String(32), nullable=False)
	external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
	raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
	original_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
	ingested_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), server_default=func.now(), nullable=False
	)

	__table_args__ = (UniqueConstraint("job_offer_id", "source", name="uq_job_offer_sources_job_offer_id_source"),)


__all__ = ["Base", "JobOffer", "JobOfferSource", "Subscription", "NotificationQueue"]


class Subscription(Base):
	"""Email subscription for new-offer notifications."""

	__tablename__ = "subscriptions"

	id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
	email: Mapped[str] = mapped_column(String(254), nullable=False)
	keywords: Mapped[list[str]] = mapped_column(
		ARRAY(Text()), nullable=False, default=list, server_default="{}"
	)
	confirmed: Mapped[bool] = mapped_column(
		Boolean(), nullable=False, default=False, server_default="false"
	)
	confirmation_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
	token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
	unsubscribe_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=False), nullable=False, server_default=func.now()
	)


_NOTIF_DEDUP = UniqueConstraint(
	"subscription_id",
	"job_offer_id",
	"notification_type",
	name="uq_notification_queue_dedup",
)


class NotificationQueue(Base):
	"""Idempotent work queue for pending email sends."""

	__tablename__ = "notification_queue"
	__table_args__ = (_NOTIF_DEDUP,)

	id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
	subscription_id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("subscriptions.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	job_offer_id: Mapped[UUID] = mapped_column(
		PGUUID(as_uuid=True),
		ForeignKey("job_offers.id", ondelete="CASCADE"),
		nullable=False,
	)
	notification_type: Mapped[str] = mapped_column(String(16), nullable=False)
	status: Mapped[str] = mapped_column(
		String(16), nullable=False, default="pending", server_default="pending", index=True
	)
	attempts: Mapped[int] = mapped_column(
		SmallInteger(), nullable=False, default=0, server_default="0"
	)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=False), nullable=False, server_default=func.now()
	)
	sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
