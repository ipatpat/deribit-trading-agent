"""Tests for DeribitClient.get_book_summary_by_currency."""

from unittest.mock import AsyncMock

import pytest

from deribit_trading.client import DeribitClient


def _make_client_with_mock_call(mock_result):
    client = DeribitClient.__new__(DeribitClient)
    client.call = AsyncMock(return_value=mock_result)  # type: ignore[method-assign]
    return client


@pytest.mark.asyncio
async def test_returns_array_shape():
    sample = [
        {"instrument_name": "BTC-27JUN26-70000-C", "mid_price": 0.05, "mark_iv": 65.2},
        {"instrument_name": "BTC-27JUN26-70000-P", "mid_price": 0.04, "mark_iv": 64.8},
    ]
    client = _make_client_with_mock_call(sample)
    result = await client.get_book_summary_by_currency("BTC", kind="option")
    assert result == sample
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_default_kind_omits_param():
    client = _make_client_with_mock_call([])
    await client.get_book_summary_by_currency("BTC")
    client.call.assert_awaited_once_with(
        "public/get_book_summary_by_currency", {"currency": "BTC"}
    )


@pytest.mark.asyncio
async def test_kind_option_passed():
    client = _make_client_with_mock_call([])
    await client.get_book_summary_by_currency("BTC", kind="option")
    client.call.assert_awaited_once_with(
        "public/get_book_summary_by_currency",
        {"currency": "BTC", "kind": "option"},
    )


@pytest.mark.asyncio
async def test_kind_future_passed():
    client = _make_client_with_mock_call([])
    await client.get_book_summary_by_currency("ETH", kind="future")
    client.call.assert_awaited_once_with(
        "public/get_book_summary_by_currency",
        {"currency": "ETH", "kind": "future"},
    )


@pytest.mark.asyncio
async def test_kind_perpetual_passed():
    client = _make_client_with_mock_call([])
    await client.get_book_summary_by_currency("BTC", kind="perpetual")
    client.call.assert_awaited_once_with(
        "public/get_book_summary_by_currency",
        {"currency": "BTC", "kind": "perpetual"},
    )
