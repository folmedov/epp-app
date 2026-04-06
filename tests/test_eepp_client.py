"""Tests for the minimal EEPP client V1."""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost/placeholder",
)

import httpx
import pytest
from decimal import Decimal

from src.ingestion.eepp_client import EEPPClient, EEPPResponseFormatError


def build_mock_client(handler: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
    """Create an async client backed by a mock transport."""

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_fetch_all_combines_and_normalizes_offers() -> None:
    """The client should merge both EEPP endpoints into a normalized list."""

    postulacion_payload = [
        {
            "Cargo": "Analista",
            "Institución / Entidad": "Servicio A",
            "Región": "Region Metropolitana",
            "Ciudad": "Santiago",
            "url": "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=139281&c=0",
            "Renta Bruta": "1000000,00",
            "TipoTxt": "Empleos P&uacute;blicos",
        }
    ]
    evaluacion_payload = [
        {
            "Cargo": "Profesional",
            "Institución / Entidad": "Servicio B",
            "Región": "Region de Valparaiso",
            "Ciudad": "Valparaiso",
            "url": "https://www.empleospublicos.cl/pub/convocatorias/convFicha.aspx?i=138525&c=0",
            "Renta Bruta": "1200000,00",
            "TipoTxt": "Empleos P&uacute;blicos Evaluaci&oacute;n",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("convocatorias2_nueva.txt"):
            return httpx.Response(200, json=postulacion_payload)
        if request.url.path.endswith("convocatorias_evaluacion_nueva.txt"):
            return httpx.Response(200, json=evaluacion_payload)
        return httpx.Response(404, json={"detail": "not found"})

    async with build_mock_client(handler) as mock_client:
        client = EEPPClient(client=mock_client)
        offers = await client.fetch_all()

    assert len(offers) == 2

    first_offer = offers[0]
    assert first_offer["source"] == "EEPP"
    assert first_offer["state"] == "postulacion"
    assert first_offer["title"] == "Analista"
    assert first_offer["institution"] == "Servicio A"
    assert first_offer["region"] == "Region Metropolitana"
    assert first_offer["city"] == "Santiago"
    assert first_offer["url"] == "https://www.empleospublicos.cl/pub/convocatorias/convpostularavisoTrabajo.aspx?i=139281&c=0"
    assert first_offer["gross_salary"] == Decimal("1000000.00")
    assert first_offer["external_id"] == "139281"
    assert isinstance(first_offer["fingerprint"], str) and len(first_offer["fingerprint"]) == 32
    assert first_offer["raw_data"] == postulacion_payload[0]

    second_offer = offers[1]
    assert second_offer["source"] == "EEPP"
    assert second_offer["state"] == "evaluacion"
    assert second_offer["title"] == "Profesional"
    assert second_offer["external_id"] == "138525"


@pytest.mark.asyncio
async def test_fetch_endpoint_rejects_non_list_payload() -> None:
    """The client should reject responses that are not lists."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async with build_mock_client(handler) as mock_client:
        client = EEPPClient(client=mock_client)

        with pytest.raises(EEPPResponseFormatError, match="must be a list"):
            await client.fetch_postulacion()