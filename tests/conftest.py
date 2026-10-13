"""Shared test fixtures.

⚠️ Importing the DM engine currently executes ``agents/dungeon_master/__init__``,
which eagerly imports the graph and therefore fetches prompt templates from
Langfuse at import time (see ``utils/prompts.py``). Tests that touch the engine
inherit that network dependency. Making the package's re-exports lazy is a
worthwhile follow-up; it is deliberately out of scope for the streaming
refactor these tests guard.
"""
from typing import Any, AsyncIterator

import pytest


class FakeSocket:
    """📼 Records ``emit`` calls as wire-equivalent tuples.

    Only ``(event, payload, to)`` is recorded. ``namespace`` is normalised
    away because python-socketio treats an omitted namespace and an explicit
    ``None`` identically (both mean the default ``/``), so the two are the
    same on the wire -- and this test suite compares implementations where one
    passes the kwarg and the other does not.
    """

    def __init__(self) -> None:
        self.emissions: list[tuple[str, dict[str, Any], str | None]] = []

    async def emit(
        self,
        event: str,
        payload: dict[str, Any] | None = None,
        to: str | None = None,
        namespace: str | None = None,
        **_: object,
    ) -> None:
        assert namespace in (None, "/"), f"unexpected namespace {namespace!r}"
        self.emissions.append((event, payload or {}, to))

    def events(self) -> list[str]:
        return [event for event, _payload, _to in self.emissions]


@pytest.fixture
def sio() -> FakeSocket:
    return FakeSocket()


async def as_stream(items: list[Any]) -> AsyncIterator[Any]:
    """Wrap a list of stream items in the async iterator the pump consumes."""
    for item in items:
        yield item


async def failing_stream(items: list[Any], exc: Exception) -> AsyncIterator[Any]:
    """Yield some items, then blow up -- exercises the pump's error boundary."""
    for item in items:
        yield item
    raise exc
