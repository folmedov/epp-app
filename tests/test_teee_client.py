"""Unit tests for the TEEE ingestion client mapping logic."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.teee_client import TEEEClient
from src.processing.transformers import compute_fingerprint


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
    expected_external = src.get("ID Conv") or hits[0].get("_id")
    expected_region = (
        src.get("Region").replace("Región de ", "") if src.get("Region") else None
    )
    expected_fingerprint = compute_fingerprint(
        "TEEE", expected_external, title=src.get("Cargo") or "", institution=src.get("Institucion/Entidad") or src.get("Institución / Entidad") or "", region=expected_region
    )

    assert norm["external_id"] == expected_external
    assert norm["region"] == expected_region
    assert norm["title"] == src.get("Cargo")
    assert norm["institution"] == (src.get("Institucion/Entidad") or src.get("Institución / Entidad"))
    assert norm["fingerprint"] == expected_fingerprint
