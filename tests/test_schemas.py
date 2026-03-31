"""Tests for the canonical job offer schema."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.core.schemas import JobOfferSchema


def test_job_offer_schema_accepts_v1_canonical_payload() -> None:
    """The schema should accept the canonical V1 contract."""

    payload = {
        "source": "EEPP",
        "title": "Analista",
        "institution": "Servicio A",
        "salary_bruto": "1000000.00",
        "state": "postulacion",
        "region": "Region Metropolitana",
        "city": "Santiago",
        "url": "https://example.com/job",
        "raw_data": {"Cargo": "Analista"},
    }

    offer = JobOfferSchema.model_validate(payload)

    assert offer.source == "EEPP"
    assert offer.title == "Analista"
    assert offer.institution == "Servicio A"
    assert offer.salary_bruto == Decimal("1000000.00")
    assert offer.state == "postulacion"
    assert offer.region == "Region Metropolitana"
    assert offer.city == "Santiago"
    assert offer.url == "https://example.com/job"
    assert offer.raw_data == {"Cargo": "Analista"}
    assert offer.fingerprint is None
    assert offer.external_id is None


def test_job_offer_schema_rejects_legacy_field_names() -> None:
    """The schema should reject the old pre-canonical field names."""

    legacy_payload = {
        "source": "EEPP",
        "source_id": "123",
        "title": "Analista",
        "sueldo_bruto": 1000000,
        "status": "postulacion",
        "json_raw": {"Cargo": "Analista"},
    }

    with pytest.raises(ValidationError):
        JobOfferSchema.model_validate(legacy_payload)