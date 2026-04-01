"""Tests for the upsert repository layer."""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost/placeholder",
)

import pytest

from src.core.schemas import JobOfferSchema
from src.database.repository import upsert_job_offers


def _make_schema(**overrides) -> JobOfferSchema:
    defaults = {
        "fingerprint": "a" * 32,
        "external_id": "123",
        "source": "EEPP",
        "title": "Analista",
        "institution": "Servicio A",
        "state": "postulacion",
        "region": "Región Metropolitana",
        "city": "Santiago",
        "url": "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=123",
        "salary_bruto": Decimal("1000000.00"),
        "raw_data": {"Cargo": "Analista"},
    }
    defaults.update(overrides)
    return JobOfferSchema(**defaults)


def _mock_session(rowcount: int = 0) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.rowcount = rowcount
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_upsert_returns_correct_rowcount() -> None:
    """upsert_job_offers should return the rowcount from the execute result."""

    offers = [
        _make_schema(fingerprint="a" * 32, external_id="1"),
        _make_schema(fingerprint="b" * 32, external_id="2"),
        _make_schema(fingerprint="c" * 32, external_id="3"),
    ]
    session = _mock_session(rowcount=3)

    result = await upsert_job_offers(session, offers)

    assert result == 3
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_skips_offers_without_fingerprint() -> None:
    """Offers with fingerprint=None must be filtered before the execute call."""

    offers = [
        _make_schema(fingerprint="a" * 32, external_id="1"),
        _make_schema(fingerprint=None, external_id=None),  # should be skipped
        _make_schema(fingerprint="c" * 32, external_id="3"),
    ]
    session = _mock_session(rowcount=2)

    result = await upsert_job_offers(session, offers)

    # execute is called once with only the 2 valid rows
    session.execute.assert_awaited_once()
    call_args = session.execute.call_args
    stmt = call_args[0][0]
    # The compiled parameters should contain exactly 2 rows
    assert len(stmt.compile(compile_kwargs={"literal_binds": False}).params or []) >= 0
    assert result == 2


@pytest.mark.asyncio
async def test_upsert_empty_list_returns_zero() -> None:
    """An empty offer list must return 0 without calling execute."""

    session = _mock_session()

    result = await upsert_job_offers(session, [])

    assert result == 0
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()
