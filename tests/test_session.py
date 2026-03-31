"""Tests for the async database connectivity layer."""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost/placeholder",
)

from types import SimpleNamespace

import pytest

from src.database import session as session_module


@pytest.mark.asyncio
async def test_get_session_yields_session_from_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session helper should yield a session created by the shared factory."""

    expected_session = SimpleNamespace(name="session")

    class FakeSessionManager:
        async def __aenter__(self) -> SimpleNamespace:
            return expected_session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_session_factory() -> FakeSessionManager:
        return FakeSessionManager()

    monkeypatch.setattr(session_module, "SessionFactory", fake_session_factory)

    async with session_module.get_session() as session:
        assert session is expected_session


@pytest.mark.asyncio
async def test_check_database_connection_executes_simple_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """The connectivity check should execute a minimal SQL statement."""

    executed: list[str] = []

    class FakeConnection:
        async def execute(self, statement) -> None:
            executed.append(str(statement))

    class FakeConnectionManager:
        async def __aenter__(self) -> FakeConnection:
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConnectionManager:
            return FakeConnectionManager()

    monkeypatch.setattr(session_module, "engine", FakeEngine())

    await session_module.check_database_connection()

    assert executed == ["SELECT 1"]