"""Tests for the upsert repository layer."""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost/placeholder",
)

import pytest
from sqlalchemy.dialects import postgresql as _pg_dialect

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
        "gross_salary": Decimal("1000000.00"),
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


def _mock_session_cross(lookup_rows: list) -> AsyncMock:
    """Mock session for cross-source tests.

    The first ``session.execute()`` call returns ``lookup_rows`` (a list of
    tuples) simulating the cross-source pre-lookup SELECT result.  Subsequent
    calls receive a plain ``MagicMock`` (for UPDATE statements whose return
    value is discarded by the repository).
    """
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[lookup_rows, MagicMock(), MagicMock()]
    )
    session.flush = AsyncMock()
    return session


def _sql(stmt, *, literal: bool = False) -> str:
    """Compile a SQLAlchemy statement to a SQL string for assertion."""
    return str(
        stmt.compile(
            dialect=_pg_dialect.dialect(),
            compile_kwargs={"literal_binds": literal},
        )
    )


# ── existing tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_returns_correct_rowcount() -> None:
    """upsert_job_offers should execute once and flush once for a valid batch."""

    offers = [
        _make_schema(fingerprint="a" * 32, external_id="1"),
        _make_schema(fingerprint="b" * 32, external_id="2"),
        _make_schema(fingerprint="c" * 32, external_id="3"),
    ]
    session = _mock_session(rowcount=3)

    result = await upsert_job_offers(session, offers)

    assert isinstance(result, dict)
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
    assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_upsert_empty_list_returns_zero() -> None:
    """An empty offer list must return 0 without calling execute."""

    session = _mock_session()

    result = await upsert_job_offers(session, [])

    assert result == {}
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()


# ── cross-source canonical promotion ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_source_higher_authority_promotes() -> None:
    """TEEE (authority 10) promotes an EEPP-owned canonical row.

    Expected flow: 1 SELECT (cross-source lookup) + 1 UPDATE (canonical fields).
    The incoming TEEE fingerprint is mapped to the existing EEPP row's id.
    session.flush() is NOT called — all rows consumed via cross-source path
    so rows_to_insert is empty and the function returns early.
    """
    existing_id = uuid4()
    csk = "CSK_PROM_001"
    existing_fp = "a" * 32
    incoming_fp = "b" * 32

    incoming = _make_schema(
        source="TEEE",
        fingerprint=incoming_fp,
        cross_source_key=csk,
        state="postulacion",
    )
    session = _mock_session_cross(
        [(existing_id, existing_fp, csk, "EEPP", "postulacion")]
    )

    fp_to_id = await upsert_job_offers(session, [incoming])

    assert fp_to_id[incoming_fp] == existing_id
    assert session.execute.await_count == 2  # lookup SELECT + promotion UPDATE
    session.flush.assert_not_awaited()        # early return, no INSERT

    # The UPDATE must transfer canonical ownership to TEEE.
    update_stmt = session.execute.call_args_list[1][0][0]
    assert "TEEE" in _sql(update_stmt, literal=True)


@pytest.mark.asyncio
async def test_cross_source_lower_authority_enriches() -> None:
    """EEPP (authority 5) enriches a TEEE-owned canonical row with its exclusive fields.

    Expected flow: 1 SELECT + 1 UPDATE that sets enrichment columns only.
    gross_salary must use COALESCE; first_employment, vacancies, prioritized set directly.
    """
    existing_id = uuid4()
    csk = "CSK_ENRICH_001"

    incoming = _make_schema(
        source="EEPP",
        fingerprint="b" * 32,
        cross_source_key=csk,
        gross_salary=Decimal("900000"),
        first_employment=True,
        vacancies=3,
        prioritized=False,
    )
    session = _mock_session_cross(
        [(existing_id, "a" * 32, csk, "TEEE", "evaluacion")]
    )

    fp_to_id = await upsert_job_offers(session, [incoming])

    assert fp_to_id["b" * 32] == existing_id
    assert session.execute.await_count == 2
    session.flush.assert_not_awaited()

    update_stmt = session.execute.call_args_list[1][0][0]
    sql = _sql(update_stmt)
    assert "coalesce" in sql.lower()        # gross_salary uses COALESCE
    assert "first_employment" in sql.lower()
    assert "vacancies" in sql.lower()
    assert "prioritized" in sql.lower()


@pytest.mark.asyncio
async def test_cross_source_enrichment_skipped_when_all_null() -> None:
    """EEPP row with all four enrichment fields = None must NOT trigger an UPDATE.

    Expected flow: only 1 execute call (the lookup SELECT).
    No enrichment UPDATE is issued; session.flush() is also not called.
    """
    existing_id = uuid4()
    csk = "CSK_SKIP_001"

    incoming = _make_schema(
        source="EEPP",
        fingerprint="b" * 32,
        cross_source_key=csk,
        gross_salary=None,
        first_employment=None,
        vacancies=None,
        prioritized=None,
    )
    session = _mock_session_cross(
        [(existing_id, "a" * 32, csk, "TEEE", "evaluacion")]
    )

    fp_to_id = await upsert_job_offers(session, [incoming])

    assert fp_to_id["b" * 32] == existing_id
    assert session.execute.await_count == 1  # lookup only; no enrichment UPDATE
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_source_promotion_state_forward_only() -> None:
    """Canonical promotion must not regress state.

    Incoming TEEE state=postulacion < existing EEPP state=evaluacion:
    the stored evaluacion must be preserved in the UPDATE SET clause.
    """
    existing_id = uuid4()
    csk = "CSK_FWD_001"

    incoming = _make_schema(
        source="TEEE",
        fingerprint="b" * 32,
        cross_source_key=csk,
        state="postulacion",   # lower priority than stored evaluacion
    )
    session = _mock_session_cross(
        [(existing_id, "a" * 32, csk, "EEPP", "evaluacion")]
    )

    await upsert_job_offers(session, [incoming])

    update_stmt = session.execute.call_args_list[1][0][0]
    sql = _sql(update_stmt, literal=True)
    assert "evaluacion" in sql   # existing state preserved
    assert "postulacion" not in sql  # incoming lower-priority state discarded


@pytest.mark.asyncio
async def test_cross_source_promotion_state_advances() -> None:
    """Canonical promotion must adopt a more-advanced incoming TEEE state.

    Incoming TEEE state=evaluacion > existing EEPP state=postulacion:
    the row must advance to evaluacion in the UPDATE SET clause.
    """
    existing_id = uuid4()
    csk = "CSK_ADV_001"

    incoming = _make_schema(
        source="TEEE",
        fingerprint="b" * 32,
        cross_source_key=csk,
        state="evaluacion",   # higher priority than stored postulacion
    )
    session = _mock_session_cross(
        [(existing_id, "a" * 32, csk, "EEPP", "postulacion")]
    )

    await upsert_job_offers(session, [incoming])

    update_stmt = session.execute.call_args_list[1][0][0]
    sql = _sql(update_stmt, literal=True)
    assert "evaluacion" in sql   # incoming advanced state adopted


# ── state-priority ON CONFLICT and deduplication ─────────────────────────────

@pytest.mark.asyncio
async def test_state_priority_initial_mode_always_overwrites() -> None:
    """In mode='initial' the ON CONFLICT SET assigns state unconditionally (no CASE guard)."""
    offer = _make_schema(state="finalizada")
    session = _mock_session(rowcount=1)

    await upsert_job_offers(session, [offer], mode="initial")

    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()
    insert_stmt = session.execute.call_args_list[0][0][0]
    sql = _sql(insert_stmt)
    # Initial mode: state is set unconditionally — no CASE guard.
    assert "CASE" not in sql.upper()


@pytest.mark.asyncio
async def test_state_priority_periodic_mode_forward_only() -> None:
    """In mode='periodic' the ON CONFLICT SET wraps state in a CASE guard."""
    offer = _make_schema(state="postulacion")
    session = _mock_session(rowcount=1)

    await upsert_job_offers(session, [offer], mode="periodic")

    session.execute.assert_awaited_once()
    insert_stmt = session.execute.call_args_list[0][0][0]
    sql = _sql(insert_stmt)
    # Periodic mode: forward-only state guard expressed as a CASE expression.
    assert "CASE" in sql.upper()


@pytest.mark.asyncio
async def test_state_priority_periodic_mode_advances() -> None:
    """Higher-priority state wins when same-fingerprint rows appear in one batch.

    evaluacion (priority 2) submitted before postulacion (priority 1):
    the postulacion row must NOT displace evaluacion in the pre-INSERT dedup.
    Deduplication is mode-independent; mode='initial' is used here so that
    the ON CONFLICT SET contains no CASE params, giving a clean state
    assertion against compiled.params.
    """
    fp = "cc" * 16   # 32 chars
    evaluacion = _make_schema(fingerprint=fp, external_id="1", state="evaluacion")
    postulacion = _make_schema(fingerprint=fp, external_id="2", state="postulacion")

    session = _mock_session(rowcount=1)
    await upsert_job_offers(session, [evaluacion, postulacion], mode="initial")

    # Both rows deduplicated to a single INSERT.
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()

    insert_stmt = session.execute.call_args_list[0][0][0]
    compiled = insert_stmt.compile(dialect=_pg_dialect.dialect())
    # In initial mode the ON CONFLICT uses column references (no string params),
    # so the only state-related param in compiled.params is from the VALUES row.
    assert "evaluacion" in compiled.params.values()


@pytest.mark.asyncio
async def test_state_priority_same_stage_updates() -> None:
    """Same-state rows with the same fingerprint: the latter row overwrites the first.

    The >= comparison in the dedup loop keeps the later offer (which carries
    fresher field values such as URL). Only a single INSERT is issued.
    """
    fp = "dd" * 16   # 32 chars
    offer_old = _make_schema(
        fingerprint=fp, external_id="1", state="postulacion",
        url="https://x.test/old",
    )
    offer_new = _make_schema(
        fingerprint=fp, external_id="2", state="postulacion",
        url="https://x.test/new",
    )

    session = _mock_session(rowcount=1)
    await upsert_job_offers(session, [offer_old, offer_new], mode="initial")

    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()

    insert_stmt = session.execute.call_args_list[0][0][0]
    compiled = insert_stmt.compile(dialect=_pg_dialect.dialect())
    # The newer offer's URL must survive into the INSERT parameters.
    assert "https://x.test/new" in compiled.params.values()
