"""Unit tests for the TEEE ingestion client mapping logic."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.teee_client import TEEEClient
from src.processing.transformers import compute_content_fingerprint, compute_fingerprint


def _load_fixture(name: str) -> dict:
    base = Path(__file__).resolve().parents[1]
    p = base / "docs" / "discovery" / name
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_normalize_first_hit_from_postulacion_fixture() -> None:
    data = _load_fixture("teee_postulacion_api_response.json")
    hits = data["hits"]["hits"]
    assert hits, "fixture should contain hits"

    client = TEEEClient()
    norm = client._normalize_hit(hits[0])

    src = hits[0]["_source"]

    raw_conv = src.get("ID Conv")
    if raw_conv not in ("", None) and str(raw_conv).strip().isdigit():
        expected_external = str(raw_conv)
        expected_generated = False
    else:
        expected_external = None  # simplified; URL extraction tested separately
        expected_generated = False  # or True for _id fallback

    expected_region = (
        src.get("Region").replace("Región de ", "") if src.get("Region") else None
    )

    assert norm["title"] == src.get("Cargo")
    assert norm["institution"] == (src.get("Institucion/Entidad") or src.get("Institución / Entidad"))
    assert norm["region"] == expected_region
    assert "content_fingerprint" in norm
    assert len(norm["content_fingerprint"]) == 32
    assert "external_id_generated" in norm
    assert "external_id_fallback_type" in norm
    # _elastic_id must appear in raw_data when _id exists on the hit
    if hits[0].get("_id"):
        assert norm["raw_data"].get("_elastic_id") == hits[0]["_id"]


def test_normalize_hit_with_numeric_id_conv_uses_stage_a() -> None:
    hit = {
        "_id": "es-abc",
        "_source": {
            "Cargo": "Analista",
            "Institucion/Entidad": "Servicio X",
            "Region": "Región Metropolitana de Santiago",
            "Ciudad": "Santiago",
            "URL": "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=999",
            "ID Conv": 12345,
            "Estado": "postulacion",
        },
    }
    client = TEEEClient()
    norm = client._normalize_hit(hit)

    assert norm["external_id"] == "12345"
    assert norm["external_id_generated"] is False
    assert norm["external_id_fallback_type"] is None
    expected_fp = compute_fingerprint(
        "TEEE", "12345",
        title="Analista", institution="Servicio X",
        region="Metropolitana de Santiago", city="Santiago",
        external_id_generated=False,
    )
    assert norm["fingerprint"] == expected_fp


def test_normalize_hit_no_id_conv_extracts_from_url() -> None:
    hit = {
        "_id": "es-xyz",
        "_source": {
            "Cargo": "Médico",
            "Institucion/Entidad": "Hospital",
            "Region": "Valparaíso",
            "Ciudad": "Valparaíso",
            "URL": "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=139189",
            "ID Conv": "",
            "Estado": "postulacion",
        },
    }
    client = TEEEClient()
    norm = client._normalize_hit(hit)

    assert norm["external_id"] == "139189"
    assert norm["external_id_generated"] is False


def test_normalize_hit_fallback_uses_teee_id_prefix_and_marks_generated() -> None:
    hit = {
        "_id": "abc123",
        "_source": {
            "Cargo": "Director",
            "Institucion/Entidad": "Municipio",
            "Region": "Los Lagos",
            "Ciudad": "Puerto Montt",
            "URL": "https://municipio.cl/cargo",
            "ID Conv": "",
            "Estado": "postulacion",
        },
    }
    client = TEEEClient()
    norm = client._normalize_hit(hit)

    assert norm["external_id"] == "teee:_id:abc123"
    assert norm["external_id_generated"] is True
    assert norm["external_id_fallback_type"] == "index_id"
    assert norm["raw_data"]["_elastic_id"] == "abc123"
    # fingerprint must use content-based stage B
    expected_fp = compute_fingerprint(
        "TEEE", "teee:_id:abc123",
        title="Director", institution="Municipio",
        region="Los Lagos", city="Puerto Montt",
        external_id_generated=True,
    )
    assert norm["fingerprint"] == expected_fp


def test_normalize_hit_content_fingerprint_always_present() -> None:
    hit = {
        "_id": "x1",
        "_source": {
            "Cargo": "Jefe",
            "Institucion/Entidad": "Servicio",
            "Region": "Atacama",
            "Ciudad": "Copiapó",
            "URL": None,
            "ID Conv": None,
            "Estado": "evaluacion",
        },
    }
    client = TEEEClient()
    norm = client._normalize_hit(hit)

    expected_cfp = compute_content_fingerprint("Jefe", "Servicio", "Atacama", "Copiapó")
    assert norm["content_fingerprint"] == expected_cfp


def test_normalize_hit_finalizada_is_normalized() -> None:
    hit = {
        "_id": "z1",
        "_source": {
            "Cargo": "X",
            "Institucion/Entidad": "Y",
            "Region": None,
            "Ciudad": None,
            "URL": None,
            "ID Conv": None,
            "Estado": "finalizadas",
        },
    }
    client = TEEEClient()
    norm = client._normalize_hit(hit)
    assert norm["state"] == "finalizada"
