"""Tests for processing transformers: extract_external_id and compute_fingerprint."""

from __future__ import annotations

import hashlib
import os
from decimal import Decimal

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost/placeholder",
)

from src.processing.transformers import compute_content_fingerprint, compute_fingerprint, extract_external_id, parse_salary


# ---------------------------------------------------------------------------
# extract_external_id
# ---------------------------------------------------------------------------


def test_extract_external_id_eepp_postulacion_url() -> None:
    url = "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=139281&c=0&j=0"
    assert extract_external_id(url) == "139281"


def test_extract_external_id_eepp_evaluacion_url() -> None:
    url = "https://www.empleospublicos.cl/pub/convocatorias/convFicha.aspx?i=138525&c=0&j=0&tipo=avisotrabajoficha"
    assert extract_external_id(url) == "138525"


def test_extract_external_id_junji_url() -> None:
    url = "https://junji.myfront.cl/oferta-de-empleo/19560/ranking-reemplazo-educadora-de-parvulos"
    assert extract_external_id(url) == "19560"


def test_extract_external_id_trabajando_simple_url() -> None:
    url = "https://externouchile.trabajando.cl/trabajo/6049750-jefe-a-de-personal-y-gestion"
    assert extract_external_id(url) == "6049750"


def test_extract_external_id_trabajando_nested_url() -> None:
    url = "https://www.trabajando.cl/trabajo-empleo/institucion/trabajo/6049069-director-a-juridica"
    assert extract_external_id(url) == "6049069"


def test_extract_external_id_difusion_url_returns_none() -> None:
    url = "https://educacionpublica.gob.cl/concursos-internos-2/2026-2/"
    assert extract_external_id(url) is None


def test_extract_external_id_generic_external_url_returns_none() -> None:
    url = "https://renca.cl/proceso-de-seleccion-prevencionista-de-riesgos-3/"
    assert extract_external_id(url) is None


def test_extract_external_id_empty_string_returns_none() -> None:
    assert extract_external_id("") is None


def test_extract_external_id_none_returns_none() -> None:
    assert extract_external_id(None) is None


# ---------------------------------------------------------------------------
# compute_content_fingerprint
# ---------------------------------------------------------------------------


def test_compute_content_fingerprint_produces_32_char_hex() -> None:
    result = compute_content_fingerprint("Analista", "Servicio A", "RM", "Santiago")
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_compute_content_fingerprint_is_case_insensitive() -> None:
    r1 = compute_content_fingerprint("Analista", "Servicio A", "RM", "Santiago")
    r2 = compute_content_fingerprint("ANALISTA", "SERVICIO A", "rm", "SANTIAGO")
    assert r1 == r2


def test_compute_content_fingerprint_none_fields_treated_as_empty() -> None:
    r1 = compute_content_fingerprint("T", "I", None, None)
    r2 = compute_content_fingerprint("T", "I", "", "")
    assert r1 == r2


def test_extract_external_id_directoresparachile_pdf() -> None:
    url = "https://directoresparachile.cl/Repositorio/PDFConcursos/dee_1967_7707.pdf?slug"
    assert extract_external_id(url) == "dee_1967_7707"


def test_compute_content_fingerprint_distinguishes_by_dates() -> None:
    r1 = compute_content_fingerprint(
        "Director(a)", "Liceo X", "Región", "Ciudad", start_date="2023-01-01", close_date="2023-02-01"
    )
    r2 = compute_content_fingerprint(
        "Director(a)", "Liceo X", "Región", "Ciudad", start_date="2023-01-01", close_date="2023-03-01"
    )
    assert r1 != r2


# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------


def test_compute_fingerprint_with_external_id() -> None:
    result = compute_fingerprint("EEPP", "139281", title="Analista", institution="Servicio A", region="RM")
    expected = hashlib.md5("source_id|EEPP|139281".encode()).hexdigest()
    assert result == expected


def test_compute_fingerprint_external_id_ignores_content_fields() -> None:
    r1 = compute_fingerprint("EEPP", "999", title="Cargo A", institution="Inst A", region="Región X")
    r2 = compute_fingerprint("EEPP", "999", title="Cargo B", institution="Inst B", region="Región Y")
    assert r1 == r2


def test_compute_fingerprint_without_external_id_uses_content_fields() -> None:
    content_fp = compute_content_fingerprint("Cargo X", "Inst Y", "Región Z", None)
    result = compute_fingerprint("DIFUSION", None, title="Cargo X", institution="Inst Y", region="Región Z")
    expected = hashlib.md5(f"content|{content_fp}".encode()).hexdigest()
    assert result == expected


def test_compute_fingerprint_without_external_id_none_region() -> None:
    content_fp = compute_content_fingerprint("Cargo X", "Inst Y", None, None)
    result = compute_fingerprint("DIFUSION", None, title="Cargo X", institution="Inst Y", region=None)
    expected = hashlib.md5(f"content|{content_fp}".encode()).hexdigest()
    assert result == expected


def test_compute_fingerprint_generated_external_id_falls_back_to_content() -> None:
    """A generated external_id must NOT be trusted for Stage-A matching."""
    r_generated = compute_fingerprint(
        "TEEE", "teee:_id:abc123",
        title="T", institution="I", region="R",
        external_id_generated=True,
    )
    r_content = compute_fingerprint(
        "TEEE", None,
        title="T", institution="I", region="R",
    )
    assert r_generated == r_content


def test_compute_fingerprint_stage_a_and_stage_b_never_collide() -> None:
    """source_id| and content| prefixes ensure different hash families."""
    r_a = compute_fingerprint("TEEE", "42", title="T", institution="I", region="R")
    r_b = compute_fingerprint("TEEE", None, title="T", institution="I", region="R")
    assert r_a != r_b


def test_compute_fingerprint_is_deterministic() -> None:
    r1 = compute_fingerprint("EEPP", "999", title="T", institution="I", region="R")
    r2 = compute_fingerprint("EEPP", "999", title="T", institution="I", region="R")
    assert r1 == r2


def test_compute_fingerprint_returns_32_char_hex() -> None:
    result = compute_fingerprint("EEPP", "123", title="T", institution="I", region=None)
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# parse_salary
# ---------------------------------------------------------------------------


def test_parse_salary_standard_eepp_format() -> None:
    assert parse_salary("594027,00") == Decimal("594027.00")


def test_parse_salary_large_value_with_thousands_dot() -> None:
    assert parse_salary("1.863.567,00") == Decimal("1863567.00")


def test_parse_salary_zero_returns_none() -> None:
    assert parse_salary("0,00") is None


def test_parse_salary_empty_string_returns_none() -> None:
    assert parse_salary("") is None


def test_parse_salary_none_returns_none() -> None:
    assert parse_salary(None) is None


def test_parse_salary_invalid_string_returns_none() -> None:
    assert parse_salary("N/A") is None
