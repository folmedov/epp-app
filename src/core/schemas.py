"""Pydantic v2 DTOs for job offers.

Schemas are used as validation / transformation contracts between
API clients, processing code and persistence layers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class JobOfferSchema(BaseModel):
    """Data transfer object representing a job offer.

    Fields should match one-to-one with the SQLAlchemy model where
    applicable to keep mapping straightforward.
    """

    id: Optional[int] = None
    source: str
    source_id: str
    title: str
    description: Optional[str] = None
    sueldo_bruto: Optional[int] = Field(
        None, description="Sueldo bruto en CLP (entero), null si no aplica"
    )
    fingerprint: str
    status: str = Field("active", description="Lifecycle state of the offer")
    json_raw: Dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"extra": "forbid"}


__all__ = ["JobOfferSchema"]
