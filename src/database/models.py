"""SQLAlchemy 2.0 models for persistence.

Defines the `JobOffer` model mapping to a Postgres table with JSONB
audit column and a unique constraint on `fingerprint` to enforce
idempotency.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class JobOffer(Base):
    """ORM model for a job offer.

    - `fingerprint` is unique and used to ensure idempotent upserts.
    - `json_raw` stores the original API response as JSONB for auditing.
    - `sueldo_bruto` stored as `Integer` (CLP) by default.
    """

    __tablename__ = "job_offers"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_job_offers_fingerprint"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    fingerprint = Column(String(64), nullable=False, index=True)
    source = Column(String(64), nullable=False)
    source_id = Column(String(128), nullable=False)
    title = Column(String(512), nullable=False)
    sueldo_bruto = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    json_raw = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<JobOffer id={self.id} fingerprint={self.fingerprint} status={self.status}>"


__all__ = ["Base", "JobOffer"]
