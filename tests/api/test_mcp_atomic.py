"""Tests for the atomic MCP tools (Phase 1 read-only)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from deribit_trading.mcp_server import create_mcp_server
from deribit_trading.models import (
    Direction,
    Greeks,
    Instrument,
    InstrumentKind,
    OptionType,
    Position,
    AccountSummary,
    Ticker,
)


def _build_server(
    *,
    market_data=None,
    portfolio=None,
    trading=None,
    smart_engine=None,
    candle_repo=None,
    env_manager=None,
):
    market_data = market_data or MagicMock()
    portfolio = portfolio or MagicMock()
    trading = trading or MagicMock()
    if not hasattr(trading, "_client") or not isinstance(trading._client, MagicMock):
        trading._client = MagicMock()
    if env_manager is None:
        env_manager = MagicMock()
        env_manager.current_env = "production"
        env_manager.is_production = MagicMock(return_value=True)
        env_manager.ws_url = "wss://www.deribit.com/ws/api/v2"
    return create_mcp_server(
        market_data=market_data,
        trading=trading,
        portfolio=portfolio,
        env_manager=env_manager,
        smart_engine=smart_engine,
        candle_repo=candle_repo,
    )


async def _call(server, name, **kwargs):
    handler = server.request_handlers
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=kwargs),
    )
    result = await handler[CallToolRequest](request)
    return json.loads(result.root.content[0].text)


# ── Discovery ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_instruments_strips_metadata():
    instruments = [
        Instrument(
            instrument_name="BTC-27JUN26-70000-C",
            kind=InstrumentKind.OPTION,
            base_currency="BTC",
            quote_currency="USD",
            contract_size=1.0,
            is_active=True,
            tick_size=0.0005,
            min_trade_amount=0.1,
            expiration_timestamp=1782345600000,
            strike=70000.0,
            option_type=OptionType.CALL,
        ),
    ]
    trading = MagicMock()
    trading._client = MagicMock()
    trading._client.get_instruments = AsyncMock(return_value=instruments)
    server = _build_server(trading=trading)
    data = await _call(server, "list_instruments", currency="BTC", kind="option")
    assert len(data) == 1
    entry = data[0]
    assert set(entry.keys()) <= {"instrument_name", "expiration_timestamp", "strike", "option_type"}
    assert "tick_size" not in entry
    assert "contract_size" not in entry


@pytest.mark.asyncio
async def test_list_expiries_dedupes_and_sorts():
    items = [
        Instrument(
            instrument_name=f"BTC-27JUN26-{strike}-C",
            kind=InstrumentKind.OPTION,
            base_currency="BTC",
            quote_currency="USD",
            contract_size=1.0,
            is_active=True,
            tick_size=0.0005,
            min_trade_amount=0.1,
            expiration_timestamp=ts,
            strike=strike,
            option_type=OptionType.CALL,
        )
        for ts, strike in [(2_000_000_000_000, 60000), (1_000_000_000_000, 70000), (1_000_000_000_000, 80000)]
    ]
    trading = MagicMock()
    trading._client = MagicMock()
    trading._client.get_instruments = AsyncMock(return_value=items)
    server = _build_server(trading=trading)
    data = await _call(server, "list_expiries", currency="BTC")
    assert len(data) == 2  # dedup
    timestamps = [d["timestamp"] for d in data]
    assert timestamps == sorted(timestamps)
    assert all(set(d.keys()) == {"expiry", "dte", "timestamp"} for d in data)


# ── get_quote (3 type branches) ───────────────────────────────────────────────


def _ticker(**kwargs) -> Ticker:
    base: dict = {
        "instrument_name": "BTC-PERPETUAL",
        "timestamp": 0,
        "mark_price": 0.0,
    }
    base.update(kwargs)
    return Ticker.model_validate(base)


@pytest.mark.asyncio
async def test_get_quote_perp_schema():
    md = MagicMock()
    md.get_ticker = AsyncMock(return_value=_ticker(
        instrument_name="BTC-PERPETUAL",
        last_price=80000,
        best_bid_price=79990,
        best_ask_price=80010,
        mark_price=80000,
        funding_8h=0.00012,
        price_change_24h=1.2,
    ))
    server = _build_server(market_data=md)
    data = await _call(server, "get_quote", instrument="BTC-PERPETUAL")
    assert data["kind"] == "perpetual"
    assert "funding_8h" in data and "change_24h" in data
    assert "iv" not in data and "delta" not in data
    assert data["mid"] == 80000
    assert data["spread_bps"] == pytest.approx((20 / 80000) * 10000)


@pytest.mark.asyncio
async def test_get_quote_option_schema():
    md = MagicMock()
    greeks = Greeks(delta=0.5, gamma=0.001, theta=-50, vega=100, rho=10)
    md.get_ticker = AsyncMock(return_value=_ticker(
        instrument_name="BTC-27JUN26-70000-C",
        last_price=0.05,
        best_bid_price=0.049,
        best_ask_price=0.051,
        mark_price=0.05,
        implied_volatility=65.2,
        underlying_price=70000,
        greeks=greeks,
    ))
    server = _build_server(market_data=md)
    data = await _call(server, "get_quote", instrument="BTC-27JUN26-70000-C")
    assert data["kind"] == "option"
    assert {"iv", "delta", "gamma", "vega", "theta", "underlying"} <= set(data.keys())
    assert "funding_8h" not in data
    assert data["delta"] == 0.5


@pytest.mark.asyncio
async def test_get_quote_future_schema():
    md = MagicMock()
    md.get_ticker = AsyncMock(return_value=_ticker(
        instrument_name="BTC-27JUN26",
        last_price=82000,
        best_bid_price=81980,
        best_ask_price=82020,
        mark_price=82000,
        index_price=80000,
    ))
    server = _build_server(market_data=md)
    data = await _call(server, "get_quote", instrument="BTC-27JUN26")
    assert data["kind"] == "future"
    assert "basis" in data and data["basis"] == 2000
    assert "iv" not in data and "funding_8h" not in data


# ── get_orderbook ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_orderbook_shape():
    md = MagicMock()
    md.get_orderbook = AsyncMock(return_value={
        "bids": [[80000, 1.5], [79990, 2.0]],
        "asks": [[80010, 1.0], [80020, 0.5]],
        "timestamp": 1700_000_000_000,
    })
    server = _build_server(market_data=md)
    data = await _call(server, "get_orderbook", instrument="BTC-PERPETUAL", depth=2)
    assert "bids" in data and "asks" in data
    assert len(data["bids"]) == 2 and len(data["asks"]) == 2


# ── get_market_snapshot ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_market_snapshot_field_slim():
    summary = [
        {
            "instrument_name": "BTC-27JUN26-70000-C",
            "mid_price": 0.05,
            "mark_iv": 65,
            "volume": 12.3,
            "open_interest": 1000,
            "bid_price": 0.049,
            "ask_price": 0.051,
            "underlying_price": 70000,
            "mark_price": 0.05,
            "creation_timestamp": 999,  # should be dropped
            "settlement_currency": "BTC",  # should be dropped
        }
    ]
    trading = MagicMock()
    trading._client = MagicMock()
    trading._client.get_book_summary_by_currency = AsyncMock(return_value=summary)
    server = _build_server(trading=trading)
    data = await _call(server, "get_market_snapshot", currency="BTC")
    assert len(data) == 1
    row = data[0]
    expected = {
        "instrument_name", "mid_price", "mark_iv", "volume_24h", "open_interest",
        "bid_price", "ask_price", "underlying_price", "mark_price",
    }
    assert set(row.keys()) == expected
    assert row["volume_24h"] == 12.3


# ── get_positions / get_balance / get_pnl_breakdown ──────────────────────────


@pytest.mark.asyncio
async def test_get_positions_field_set():
    pos = Position(
        instrument_name="BTC-PERPETUAL",
        kind=InstrumentKind.FUTURE,
        direction=Direction.BUY,
        size=100.0,
        average_price=80000.0,
        mark_price=81000.0,
        floating_profit_loss=0.001,
        total_profit_loss=0.001,
        delta=1.0,
        leverage=10,
    )
    trading = MagicMock()
    trading._client = MagicMock()
    trading._client.get_positions = AsyncMock(return_value=[pos])
    server = _build_server(trading=trading)
    data = await _call(server, "get_positions", currency="BTC")
    assert len(data) == 1
    keys = set(data[0].keys())
    assert {"instrument", "size", "direction", "entry_price", "mark_price",
            "delta", "pnl_btc", "pnl_usd", "leverage"} <= keys


@pytest.mark.asyncio
async def test_get_balance_field_set():
    acc = AccountSummary(
        currency="BTC",
        equity=1.5,
        balance=1.4,
        margin_balance=1.5,
        available_funds=1.2,
        initial_margin=0.3,
        maintenance_margin=0.1,
        total_pl=0.05,
    )
    trading = MagicMock()
    trading._client = MagicMock()
    trading._client.get_account_summary = AsyncMock(return_value=acc)
    server = _build_server(trading=trading)
    data = await _call(server, "get_balance", currency="BTC")
    expected = {"currency", "equity", "balance", "available", "margin_used",
                "im_ratio", "mm_ratio", "total_pnl"}
    assert expected <= set(data.keys())
    assert data["im_ratio"] == pytest.approx(0.3 / 1.5)


@pytest.mark.asyncio
async def test_get_pnl_breakdown_sorted_with_pct():
    portfolio = MagicMock()
    portfolio.get_pnl_attribution = AsyncMock(return_value=[
        {"instrument": "A", "total_pnl": -0.02, "direction": "buy", "size": 1, "realized_pnl": 0, "unrealized_pnl": -0.02},
        {"instrument": "B", "total_pnl": 0.05, "direction": "buy", "size": 1, "realized_pnl": 0, "unrealized_pnl": 0.05},
    ])
    server = _build_server(portfolio=portfolio)
    data = await _call(server, "get_pnl_breakdown", currency="BTC")
    assert [d["instrument"] for d in data] == ["B", "A"]
    assert sum(d["pct_of_total"] for d in data) == pytest.approx(100.0)


# ── get_risk_status / get_system_status ──────────────────────────────────────


@pytest.mark.asyncio
async def test_get_risk_status_required_fields():
    rm = MagicMock()
    rm.get_risk_status = MagicMock(return_value={
        "daily_pnl": 100.0,
        "trading_paused": False,
        "config": {
            "daily_loss_limit_usd": 5000,
            "max_position_size": 10,
        },
    })
    smart_engine = MagicMock()
    smart_engine._risk_manager = rm
    server = _build_server(smart_engine=smart_engine)
    data = await _call(server, "get_risk_status")
    expected = {"daily_pnl", "daily_limit", "paused",
                "max_position_size", "current_order_rate"}
    assert expected <= set(data.keys())
    assert data["daily_limit"] == 5000


@pytest.mark.asyncio
async def test_get_system_status_required_fields():
    server = _build_server()
    data = await _call(server, "get_system_status")
    expected = {"env", "connected", "authenticated", "ws_url", "fees", "uptime_sec"}
    assert expected <= set(data.keys())
    assert "maker" in data["fees"] or "perp_maker" in data["fees"]
