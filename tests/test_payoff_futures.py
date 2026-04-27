"""Tests for futures support in the payoff API."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from deribit_trading.rest_api import create_rest_app
from deribit_trading.config import EnvManager


def _make_mock_services():
    """Create mock services for the REST app."""
    market_data = MagicMock()
    trading = MagicMock()
    trading._client = MagicMock()
    portfolio = MagicMock()
    env_manager = MagicMock(spec=EnvManager)
    env_manager.current_env = "test"
    return market_data, trading, portfolio, env_manager


def _make_option_ticker(strike: float, opt_type: str, underlying: float = 95000.0):
    """Create a mock option ticker response."""
    delta = 0.5 if opt_type == "C" else -0.5
    return {
        "mark_price": 0.04,
        "best_bid_price": 0.038,
        "best_ask_price": 0.042,
        "underlying_price": underlying,
        "greeks": {"delta": delta, "theta": -0.001},
    }


def _make_future_ticker(mark_price: float = 95000.0):
    """Create a mock futures ticker response."""
    return {
        "mark_price": mark_price,
        "best_bid_price": mark_price - 5,
        "best_ask_price": mark_price + 5,
        "underlying_price": mark_price,
    }


@pytest.fixture
def app_and_trading():
    market_data, trading, portfolio, env_manager = _make_mock_services()
    app = create_rest_app(market_data, trading, portfolio, env_manager)
    return app, trading


@pytest.mark.asyncio
async def test_pure_futures_payoff(app_and_trading):
    """A pure futures leg should produce a payoff curve."""
    app, trading = app_and_trading
    trading._client.call = AsyncMock(return_value=_make_future_ticker(95000.0))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/options/payoff", json={
            "legs": [{"instrument": "BTC-PERPETUAL", "direction": "buy", "amount": 1}],
            "points": 10,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["payoff_btc"]) == 10
    assert len(data["payoff_usd"]) == 10
    assert data["legs"][0]["type"] == "future"
    assert data["legs"][0]["entry_price"] == 95000.0
    assert data["legs"][0]["delta"] == 1  # buy = +1
    assert data["legs"][0]["theta"] == 0

    # At entry price, PnL should be ~0
    mid = data["payoff_btc"][len(data["payoff_btc"]) // 2]
    # Above entry → profit for long futures
    above = data["payoff_btc"][-1]
    assert above["pnl"] > 0


@pytest.mark.asyncio
async def test_mixed_option_futures_payoff(app_and_trading):
    """A mixed option+futures combo should compute and merge correctly."""
    app, trading = app_and_trading

    async def mock_call(method, params):
        inst = params["instrument_name"]
        if "PERPETUAL" in inst:
            return _make_future_ticker(95000.0)
        else:
            return _make_option_ticker(95000, "C", 95000.0)

    trading._client.call = AsyncMock(side_effect=mock_call)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/options/payoff", json={
            "legs": [
                {"instrument": "BTC-27JUN25-95000-C", "direction": "buy", "amount": 1},
                {"instrument": "BTC-PERPETUAL", "direction": "sell", "amount": 0.5},
            ],
            "points": 10,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["legs"]) == 2
    assert data["legs"][0]["type"] == "call"
    assert data["legs"][1]["type"] == "future"

    # Net delta = option_delta + futures_delta
    summary = data["summary"]
    assert "net_delta" in summary
    assert "net_theta" in summary


@pytest.mark.asyncio
async def test_invalid_instrument_rejected(app_and_trading):
    """An invalid instrument name should return 400."""
    app, trading = app_and_trading

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/options/payoff", json={
            "legs": [{"instrument": "INVALID", "direction": "buy", "amount": 1}],
        })

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_dated_future_instrument(app_and_trading):
    """A dated future like BTC-27JUN25 should be recognized as future."""
    app, trading = app_and_trading
    trading._client.call = AsyncMock(return_value=_make_future_ticker(96000.0))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/options/payoff", json={
            "legs": [{"instrument": "BTC-27JUN25", "direction": "sell", "amount": 1}],
            "points": 10,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["legs"][0]["type"] == "future"
    assert data["legs"][0]["delta"] == -1  # sell = -1


@pytest.mark.asyncio
async def test_existing_option_only_still_works(app_and_trading):
    """Existing option-only payoff should not be broken."""
    app, trading = app_and_trading
    trading._client.call = AsyncMock(return_value=_make_option_ticker(90000, "P", 95000.0))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/options/payoff", json={
            "legs": [{"instrument": "BTC-27JUN25-90000-P", "direction": "buy", "amount": 1}],
            "points": 10,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["legs"][0]["type"] == "put"
    assert len(data["payoff_btc"]) == 10
    assert "breakeven" in data["summary"]
