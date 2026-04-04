"""Pydantic v2 DTOs for job offers.

Schemas are used as validation / transformation contracts between
API clients, processing code and persistence layers.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobOfferSchema(BaseModel):
    """Data transfer object representing a job offer.

    Fields should match one-to-one with the SQLAlchemy model where
    applicable to keep mapping straightforward.
    """

    id: UUID | None = None
    fingerprint: str | None = None
    external_id: str | None = None
    external_id_generated: bool = False
    external_id_fallback_type: str | None = None
    content_fingerprint: str | None = None
    source: str
    title: str
    institution: str
    salary_bruto: Decimal | None = Field(
        None,
        description="Monthly gross salary in CLP, null when not available",
    )
    state: str
    region: str | None = None
    city: str | None = None
    url: str | None = None
    ministry: str | None = None
    start_date: str | None = None
    close_date: str | None = None
    conv_type: str | None = None
    raw_data: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(extra="forbid", from_attributes=True)


__all__ = ["JobOfferSchema"]
