"""Async client for fetching active job offers from EEPP.

This V1 client is intentionally small. It focuses on extracting raw offers
from the public EEPP endpoints, attaching their source state, and preserving
the original payload for later processing stages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.core.config import settings


LOGGER = logging.getLogger(__name__)


class EEPPClientError(Exception):
	"""Base exception for EEPP client failures."""


class EEPPResponseFormatError(EEPPClientError):
	"""Raised when an EEPP endpoint returns an unexpected payload."""


class EEPPClient:
	"""Minimal async client for EEPP public job offer endpoints."""

	POSTULACION_URL = "https://www.empleospublicos.cl/data/convocatorias2_nueva.txt"
	EVALUACION_URL = "https://www.empleospublicos.cl/data/convocatorias_evaluacion_nueva.txt"
	SOURCE_NAME = "EEPP"

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
		"""Build the minimal V1 internal representation for an EEPP offer."""

		return {
			"source": self.SOURCE_NAME,
			"state": state,
			"title": raw_offer.get("Cargo"),
			"institution": raw_offer.get("Institución / Entidad"),
			"region": raw_offer.get("Región"),
			"city": raw_offer.get("Ciudad"),
			"url": raw_offer.get("url"),
			"salary_raw": raw_offer.get("Renta Bruta"),
			"raw_data": raw_offer,
		}


__all__ = [
	"EEPPClient",
	"EEPPClientError",
	"EEPPResponseFormatError",
]
