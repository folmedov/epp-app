"""Async client for TrabajaEnElEstado (TEEE) Elasticsearch endpoint.

This client queries the Elasticsearch proxy described in docs/discovery/teee_api.md
and normalizes each hit into the project's canonical job-offer dict shape used by
the ingestion/upsert pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import settings
from src.processing.transformers import compute_fingerprint, extract_external_id


LOGGER = logging.getLogger(__name__)


class TEEEClientError(Exception):
    """Base exception for TEEE client failures."""


class TEEEResponseFormatError(TEEEClientError):
    """Raised when the TEEE endpoint returns an unexpected payload."""


class TEEEClient:
    """Minimal async client for the TEEE Elasticsearch endpoint.

    Public methods mirror the EEPP client: `fetch_postulacion`, `fetch_evaluacion`,
    `fetch_finalizado` and `fetch_all`. Each returns a list of normalized dicts.
    """

    ENDPOINT = "https://elastic.serviciocivil.cl/listado_teee/_doc/_search"

    def __init__(self, timeout: Optional[float] = None, client: Optional[httpx.AsyncClient] = None) -> None:
        self._timeout = float(timeout) if timeout is not None else float(settings.SCRAPER_TIMEOUT)
        self._client = client

    async def fetch_postulacion(self) -> List[Dict[str, Any]]:
        return await self._fetch_state("postulacion")

    async def fetch_evaluacion(self) -> List[Dict[str, Any]]:
        return await self._fetch_state("evaluacion")

    async def fetch_finalizado(self) -> List[Dict[str, Any]]:
        return await self._fetch_state("finalizadas")

    async def fetch_all(self) -> List[Dict[str, Any]]:
        postulacion, evaluacion, finalizado = await httpx.AsyncClient().gather(
            self.fetch_postulacion(), self.fetch_evaluacion(), self.fetch_finalizado()
        )
        return [*postulacion, *evaluacion, *finalizado]

    async def _fetch_state(self, state: str, size: int = 36, max_pages: int = 1000) -> List[Dict[str, Any]]:
        """Fetch all hits for a given `Estado` value, paginating via `from`/`size`.

        The method will stop when no more hits are returned or when `max_pages` is
        reached to avoid runaway requests.
        """
        results: List[Dict[str, Any]] = []

        async def _do_post(body: Dict[str, Any]) -> Dict[str, Any]:
            try:
                if self._client is not None:
                    resp = await self._client.post(self.ENDPOINT, json=body)
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        resp = await client.post(self.ENDPOINT, json=body)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                LOGGER.exception("Failed to fetch TEEE state=%s", state)
                raise TEEEClientError("Failed to fetch TEEE data") from exc
            except ValueError as exc:
                LOGGER.exception("Failed to decode TEEE state=%s response", state)
                raise TEEEResponseFormatError("TEEE response is not valid JSON") from exc

        page = 0
        while page < max_pages:
            body = {
                "from": page * size,
                "size": size,
                "query": {"bool": {"must": [{"term": {"Estado": state}}]}},
            }
            payload = await _do_post(body)

            # validate structure
            if not isinstance(payload, dict) or "hits" not in payload or "hits" not in payload["hits"]:
                raise TEEEResponseFormatError("Unexpected TEEE payload structure")

            hits = payload["hits"]["hits"]
            if not hits:
                break

            for hit in hits:
                results.append(self._normalize_hit(hit))

            # if fewer than requested, we've reached the end
            if len(hits) < size:
                break
            page += 1

        return results

    def _normalize_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize an individual Elasticsearch hit to the canonical shape.

        Expected `hit` structure: {"_id": ..., "_source": {...}} as in discovery fixtures.
        """
        src = hit.get("_source") or hit.get("_doc") or {}
        # In fixtures the payload lives under `_source`
        if not isinstance(src, dict):
            src = {}

        # fields mapping
        title = src.get("Cargo")
        institution = src.get("Institucion/Entidad") or src.get("Institución / Entidad")
        raw_region = src.get("Region")
        region = self._normalize_region(raw_region)
        city = src.get("Ciudad")
        url = src.get("URL") or None

        # external id: prefer explicit ID Conv, then extract from URL, then use hit _id
        external_id = src.get("ID Conv")
        if external_id in ("", None):
            external_id = extract_external_id(url) if url else None
        if external_id in ("", None):
            external_id = hit.get("_id")

        # state normalization: map plural finalizadas -> finalizada
        raw_state = (src.get("Estado") or "").lower()
        if raw_state == "finalizadas":
            state = "finalizada"
        else:
            state = raw_state or None

        fingerprint = compute_fingerprint(
            "TEEE", external_id, title=title or "", institution=institution or "", region=region
        )

        return {
            "source": "TEEE",
            "state": state,
            "title": title,
            "institution": institution,
            "region": region,
            "city": city,
            "url": url or None,
            "salary_bruto": None,
            "external_id": external_id,
            "fingerprint": fingerprint,
            "raw_data": src,
        }

    @staticmethod
    def _normalize_region(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        # Normalize by removing leading 'Región de ' prefix when present
        if raw.startswith("Región de "):
            return raw[len("Región de "):].strip()
        return raw


__all__ = ["TEEEClient", "TEEEClientError", "TEEEResponseFormatError"]
