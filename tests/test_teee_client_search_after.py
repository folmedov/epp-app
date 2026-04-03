"""Tests for TEEEClient search_after pagination behavior."""

from __future__ import annotations

import asyncio

from src.ingestion.teee_client import TEEEClient


class DummyResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


class DummyClient:
    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, timeout: float | None = None):
        idx = len(self.calls)
        self.calls.append(json)
        data = self._responses[idx] if idx < len(self._responses) else {"hits": {"hits": []}}
        return DummyResponse(data)


def _make_hit(id_: str, sort_vals: list) -> dict:
    return {"_id": id_, "_source": {"Cargo": "X", "Institucion/Entidad": "Y", "Region": "Región Z", "URL": "http://"}, "sort": sort_vals}


def test_fetch_state_search_after_iterates_and_uses_search_after():
    # prepare two pages with one hit each, then an empty page
    responses = [
        {"hits": {"hits": [_make_hit("id1", [1, 100])] } },
        {"hits": {"hits": [_make_hit("id2", [2, 200])] } },
        {"hits": {"hits": []}},
    ]

    dummy = DummyClient(responses)
    client = TEEEClient(client=dummy, use_search_after=True, use_pit=False)

    results = asyncio.run(client._fetch_state("finalizadas", size=1, max_pages=0))

    assert len(results) == 2
    # ensure the second call included the search_after cursor from the first hit
    assert len(dummy.calls) >= 2
    assert "search_after" in dummy.calls[1]
    assert dummy.calls[1]["search_after"] == responses[0]["hits"]["hits"][-1]["sort"]
