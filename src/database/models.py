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

from sqlalchemy import DateTime, Numeric, String, func, ForeignKey, UniqueConstraint
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
	salary_bruto: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
	state: Mapped[str] = mapped_column(String(32), nullable=False)
	region: Mapped[str | None] = mapped_column(String(255), nullable=True)
	city: Mapped[str | None] = mapped_column(String(255), nullable=True)
	url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
	ministry: Mapped[str | None] = mapped_column(String(255), nullable=True)
	start_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
	close_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
	conv_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

	__table_args__ = (UniqueConstraint("source", "external_id"),)


__all__ = ["Base", "JobOffer", "JobOfferSource"]
