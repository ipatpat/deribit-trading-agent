"""Tests for POST /api/v1/agent/confirm/{tool_call_id}."""

import asyncio

import pytest

from deribit_trading.agent.loop import (
    _pending_confirmations,
    has_pending_confirmation,
    resolve_confirmation,
)


@pytest.fixture(autouse=True)
def _reset_pending():
    _pending_confirmations.clear()
    yield
    _pending_confirmations.clear()


def test_resolve_confirmation_returns_false_when_unknown():
    assert resolve_confirmation("tc_unknown", True) is False


@pytest.mark.asyncio
async def test_resolve_confirmation_sets_pending_future():
    fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    _pending_confirmations["tc_1"] = fut
    assert has_pending_confirmation("tc_1") is True
    ok = resolve_confirmation("tc_1", True)
    assert ok is True
    assert fut.done()
    assert fut.result() is True


@pytest.mark.asyncio
async def test_resolve_confirmation_with_false():
    fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    _pending_confirmations["tc_2"] = fut
    resolve_confirmation("tc_2", False)
    assert fut.result() is False


@pytest.mark.asyncio
async def test_resolve_confirmation_returns_false_when_already_resolved():
    fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    _pending_confirmations["tc_3"] = fut
    assert resolve_confirmation("tc_3", True) is True
    # Second call must NOT raise InvalidStateError; should return False
    assert resolve_confirmation("tc_3", False) is False
