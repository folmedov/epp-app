"""Async client for TrabajaEnElEstado (TEEE) Elasticsearch endpoint.

This client queries the Elasticsearch proxy and normalizes each hit into the
project's canonical job-offer dict shape used by the ingestion/upsert pipeline.
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import settings
from src.processing.transformers import compute_content_fingerprint, compute_fingerprint, compute_cross_source_key, extract_external_id, parse_date


LOGGER = logging.getLogger(__name__)


class TEEEClientError(Exception):
	"""Base exception for TEEE client failures."""


class TEEEResponseFormatError(TEEEClientError):
	"""Raised when the TEEE endpoint returns an unexpected payload."""


class TEEEClient:
	"""Minimal async client for the TEEE Elasticsearch endpoint.

	Public methods mirror the EEPP client: `fetch_postulacion`,
	`fetch_evaluacion`, `fetch_finalizado` and `fetch_all`. Each returns a
	list of normalized dicts.
	"""

	ENDPOINT = "https://elastic.serviciocivil.cl/listado_teee/_doc/_search"

	def __init__(
		self,
		timeout: Optional[float] = None,
		client: Optional[httpx.AsyncClient] = None,
		*,
		use_search_after: bool = True,
		use_pit: bool = False,
	) -> None:
		self._timeout = float(timeout) if timeout is not None else float(settings.SCRAPER_TIMEOUT)
		self._client = client
		# pagination strategy flags
		self.use_search_after = bool(use_search_after)
		self.use_pit = bool(use_pit)

	async def fetch_postulacion(self) -> List[Dict[str, Any]]:
		return await self._fetch_state("postulacion")

	async def fetch_evaluacion(self) -> List[Dict[str, Any]]:
		return await self._fetch_state("evaluacion")

	async def fetch_finalizado(self) -> List[Dict[str, Any]]:
		return await self._fetch_state("finalizadas")

	async def fetch_all(self) -> List[Dict[str, Any]]:
		# run the three fetches concurrently
		postulacion, evaluacion, finalizado = await asyncio.gather(
			self.fetch_postulacion(), self.fetch_evaluacion(), self.fetch_finalizado()
		)
		return [*postulacion, *evaluacion, *finalizado]

	async def _fetch_state(self, state: str, size: int = 1000, max_pages: int = 0) -> List[Dict[str, Any]]:
		"""Fetch all hits for a given `Estado` value.

		Supports `search_after` and a fallback to offset pagination.
		"""
		results: List[Dict[str, Any]] = []

		async def _do_post(body: Dict[str, Any]) -> Dict[str, Any]:
			try:
				if self._client is not None:
					resp = await self._client.post(self.ENDPOINT, json=body, timeout=self._timeout)
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

		# search_after strategy
		if self.use_search_after:
			last_sort = None
			page = 0

			# stable sort using Datesum + _id (Datesum exists in TEEE mapping)
			sort_clause = [{"Datesum": "asc"}, {"_id": "asc"}]

			while True:
				body: Dict[str, Any] = {
					"size": size,
					"query": {"bool": {"must": [{"term": {"Estado": state}}]}},
					"sort": sort_clause,
				}
				if last_sort is not None:
					body["search_after"] = last_sort

				payload = await _do_post(body)

				if not isinstance(payload, dict) or "hits" not in payload or "hits" not in payload["hits"]:
					raise TEEEResponseFormatError("Unexpected TEEE payload structure")

				hits = payload["hits"]["hits"]
				if not hits:
					break

				for hit in hits:
					results.append(self._normalize_hit(hit))

				last = hits[-1].get("sort")
				if last is None:
					raise TEEEResponseFormatError("search_after requires hits to include 'sort' values")
				last_sort = last

				page += 1
				if max_pages and page >= max_pages:
					break

			return results

		# fallback: offset pagination
		page = 0
		while page < (max_pages or 1000):
			body = {
				"from": page * size,
				"size": size,
				"query": {"bool": {"must": [{"term": {"Estado": state}}]}},
			}
			payload = await _do_post(body)

			if not isinstance(payload, dict) or "hits" not in payload or "hits" not in payload["hits"]:
				raise TEEEResponseFormatError("Unexpected TEEE payload structure")

			hits = payload["hits"]["hits"]
			if not hits:
				break

			for hit in hits:
				results.append(self._normalize_hit(hit))

			if len(hits) < size:
				break
			page += 1

		return results

	def _normalize_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
		"""Normalize an individual Elasticsearch hit to the canonical shape.

		Expected `hit` structure: {"_id": ..., "_source": {...}}.
		"""
		src = hit.get("_source") or hit.get("_doc") or {}
		if not isinstance(src, dict):
			src = {}

		title = src.get("Cargo")
		institution = src.get("Institucion/Entidad") or src.get("Institución / Entidad")
		raw_region = src.get("Region")
		region = self._normalize_region(raw_region)
		city = src.get("Ciudad")
		url = src.get("URL") or None

		# Stage-A: prefer numeric ID Conv
		external_id_generated = False
		external_id_fallback_type: Optional[str] = None
		raw_conv = src.get("ID Conv")
		if raw_conv not in ("", None) and str(raw_conv).strip().isdigit():
			external_id: Optional[str] = str(raw_conv)
		else:
			# Stage-A fallback: try to extract from URL
			external_id = extract_external_id(url) if url else None

		if external_id in ("", None):
			# Stage-B: use Elasticsearch _id as a generated fallback
			_es_id = hit.get("_id")
			if _es_id is not None:
				external_id = f"teee:_id:{_es_id}"
				external_id_generated = True
				external_id_fallback_type = "index_id"
			else:
				external_id = None

		raw_state = (src.get("Estado") or "").lower()
		if raw_state == "finalizadas":
			state = "finalizada"
		else:
			state = raw_state or None

		# Extract additional fields used to enrich the content fingerprint
		ministry = src.get("Ministerio")
		start_date = parse_date(src.get("Fecha inicio Convocatoria"))
		conv_type = src.get("Tipo Convocatoria")
		close_date = parse_date(src.get("Fecha cierre Convocatoria"))

		# Always compute a content fingerprint for cross-source matching
		content_fingerprint = compute_content_fingerprint(
			title or "",
			institution or "",
			region,
			city,
			ministry=ministry,
			start_date=start_date,
			conv_type=conv_type,
			close_date=close_date,
		)

		fingerprint = compute_fingerprint(
			"TEEE",
			external_id,
			title=title or "",
			institution=institution or "",
			region=region,
			city=city,
			external_id_generated=external_id_generated,
			ministry=ministry,
			start_date=start_date,
			conv_type=conv_type,
			close_date=close_date,
			url=url,
		)

		# Include the Elasticsearch _id in raw_data for traceability
		raw_data = dict(src)
		if hit.get("_id") is not None:
			raw_data["_elastic_id"] = hit.get("_id")

		return {
			"source": "TEEE",
			"state": state,
			"title": title,
			"institution": institution,
			"region": region,
			"city": city,
			"url": url or None,
			"gross_salary": None,
			"external_id": external_id,
			"external_id_generated": external_id_generated,
			"external_id_fallback_type": external_id_fallback_type,
			"content_fingerprint": content_fingerprint,
			"fingerprint": fingerprint,
			"cross_source_key": compute_cross_source_key(external_id, external_id_generated, url=url or None),
			"ministry": ministry,
			"start_date": start_date,
			"close_date": close_date,
			"conv_type": conv_type,
			"raw_data": raw_data,
		}

	@staticmethod
	def _normalize_region(raw: Optional[str]) -> Optional[str]:
		if not raw:
			return None
		if raw.startswith("Región de "):
			return raw[len("Región de "):].strip()
		return raw


__all__ = ["TEEEClient", "TEEEClientError", "TEEEResponseFormatError"]

