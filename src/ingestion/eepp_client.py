"""Async client for fetching active job offers from EEPP.

This V1 client is intentionally small. It focuses on extracting raw offers
from the public EEPP endpoints, attaching their source state, and preserving
the original payload for later processing stages.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

import httpx

from src.core.config import settings
from src.core.regions import normalize_region_from_text
from src.processing.transformers import (
	compute_fingerprint,
	compute_content_fingerprint,
	compute_cross_source_key,
	extract_external_id,
	parse_date,
	parse_salary,
)

_TIPOTXT_TO_SOURCE: dict[str, str] = {
    "Empleos Públicos": "EEPP",
    "Empleos Públicos Evaluación": "EEPP",
    "JUNJI": "JUNJI",
    "Invitación a Postular": "EXTERNAL",
    "DIFUSION": "DIFUSION",
    "Comisión Mercado Financiero": "CMF",
}


LOGGER = logging.getLogger(__name__)


def _parse_vacancies(value: object) -> int | None:
	"""Parse EEPP 'Nº de Vacantes' (string digit) to int, or None on failure."""
	if value is None:
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _parse_bool_str(value: object) -> bool | None:
	"""Parse EEPP boolean-as-string fields (e.g. 'True'/'False') to bool."""
	if value is None:
		return None
	if isinstance(value, bool):
		return value
	return str(value).strip().lower() == "true"


class EEPPClientError(Exception):
	"""Base exception for EEPP client failures."""


class EEPPResponseFormatError(EEPPClientError):
	"""Raised when an EEPP endpoint returns an unexpected payload."""


class EEPPClient:
	"""Minimal async client for EEPP public job offer endpoints."""

	POSTULACION_URL = "https://www.empleospublicos.cl/data/convocatorias2_nueva.txt"
	EVALUACION_URL = "https://www.empleospublicos.cl/data/convocatorias_evaluacion_nueva.txt"

	def __init__(
		self,
		timeout: float | None = None,
		client: httpx.AsyncClient | None = None,
	) -> None:
		self._timeout = timeout if timeout is not None else float(settings.SCRAPER_TIMEOUT)
		self._client = client

	async def fetch_postulacion(self) -> list[dict[str, Any]]:
		"""Fetch active EEPP offers in postulacion state."""

		return await self._fetch_endpoint(self.POSTULACION_URL, "postulacion")

	async def fetch_evaluacion(self) -> list[dict[str, Any]]:
		"""Fetch active EEPP offers in evaluacion state."""

		return await self._fetch_endpoint(self.EVALUACION_URL, "evaluacion")

	async def fetch_all(self) -> list[dict[str, Any]]:
		"""Fetch and combine postulacion and evaluacion offers."""

		postulacion, evaluacion = await asyncio.gather(
			self.fetch_postulacion(),
			self.fetch_evaluacion(),
		)
		return [*postulacion, *evaluacion]

	async def _fetch_endpoint(self, url: str, state: str) -> list[dict[str, Any]]:
		"""Fetch an EEPP endpoint and normalize its records."""

		try:
			if self._client is not None:
				response = await self._client.get(url)
			else:
				async with httpx.AsyncClient(timeout=self._timeout) as client:
					response = await client.get(url)

			response.raise_for_status()
			payload = response.json()
		except httpx.HTTPError as exc:
			LOGGER.exception("Failed to fetch EEPP %s offers", state)
			raise EEPPClientError(f"Failed to fetch EEPP {state} offers") from exc
		except ValueError as exc:
			LOGGER.exception("Failed to decode EEPP %s response", state)
			raise EEPPResponseFormatError(
				f"EEPP {state} response is not valid JSON"
			) from exc

		if not isinstance(payload, list):
			raise EEPPResponseFormatError(
				f"EEPP {state} response must be a list of offers"
			)

		normalized_offers: list[dict[str, Any]] = []
		for item in payload:
			if not isinstance(item, dict):
				raise EEPPResponseFormatError(
					f"EEPP {state} response contains a non-object item"
				)
			normalized_offers.append(self._normalize_offer(item, state))

		return normalized_offers

	def _normalize_offer(self, raw_offer: dict[str, Any], state: str) -> dict[str, Any]:
		"""Build the V1 internal representation for an EEPP offer."""

		tipo_txt = html.unescape(raw_offer.get("TipoTxt") or "")
		source = _TIPOTXT_TO_SOURCE.get(tipo_txt, "EEPP")

		url: str = raw_offer.get("url") or ""
		title: str | None = raw_offer.get("Cargo")
		institution: str | None = raw_offer.get("Institución / Entidad")
		region: str | None = normalize_region_from_text(raw_offer.get("Región"))

		external_id = extract_external_id(url)

		# EEPP exposes some ministry/date fields in its payload; include them when present
		ministry = raw_offer.get("Ministerio")
		start_date = parse_date(raw_offer.get("Fecha Inicio") or raw_offer.get("Fecha Inicio Convocatoria"))
		close_date = parse_date(raw_offer.get("Fecha Cierre Convocatoria"))

		content_fingerprint = compute_content_fingerprint(
			title or "",
			institution or "",
			region,
			raw_offer.get("Ciudad"),
			ministry=ministry,
			start_date=start_date,
			conv_type=None,
			close_date=close_date,
		)

		fingerprint = compute_fingerprint(
			source,
			external_id,
			title=title or "",
			institution=institution or "",
			region=region,
			city=raw_offer.get("Ciudad"),
			ministry=ministry,
			start_date=start_date,
			conv_type=None,
			close_date=close_date,
			url=url or None,
		)

		return {
			"source": source,
			"state": state,
			"title": title,
			"institution": institution,
			"region": region,
			"city": raw_offer.get("Ciudad"),
			"url": url or None,
			"gross_salary": parse_salary(raw_offer.get("Renta Bruta")),
			"external_id": external_id,
			"external_id_generated": False,
			"external_id_fallback_type": None,
			"content_fingerprint": content_fingerprint,
			"fingerprint": fingerprint,
			"cross_source_key": compute_cross_source_key(external_id, False, url=url or None),
			"ministry": ministry,
			"start_date": start_date,
			"close_date": close_date,
			"conv_type": None,
			"first_employment": raw_offer.get("esPrimerEmpleo"),
			"vacancies": _parse_vacancies(raw_offer.get("Nº de Vacantes")),
			"prioritized": _parse_bool_str(raw_offer.get("Priorizado")),
			"raw_data": raw_offer,
		}


__all__ = [
	"EEPPClient",
	"EEPPClientError",
	"EEPPResponseFormatError",
]
