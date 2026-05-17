"""Tests for the smart order engine.

Local tests: types, fee logic (no network).
API tests: SmartOrder on testnet (require DERIBIT_CLIENT_ID).
Intent algorithm tests live in tests/smart_order/.
"""

import os

import pytest

from deribit_trading.smart_order.types import (
    Action,
    FeeContext,
    MarketSnapshot,
    MyOrderState,
    OrderBookLevel,
    OrderBookSnapshot,
    SmartOrderConfig,
    SmartOrderState,
    TickerSnapshot,
)
from deribit_trading.smart_order.fee_logic import (
    build_fee_context,
    classify_instrument,
    fee_savings_estimate,
)
from deribit_trading.algorithms import get_algorithm, list_algorithms
import deribit_trading.algorithms.intent_router  # noqa: F401  -- registers intent:* names


# ── Fixtures ────────────────────────────────────────────────────────

def make_snapshot(
    best_bid: float = 94000,
    best_ask: float = 94010,
    my_price: float = 94000,
    direction: str = "buy",
    elapsed_ms: int = 0,
    timeout_ms: int | None = 120000,
    tick_size: float = 0.5,
    amend_count: int = 0,
    price_limit: float | None = None,
    instrument_type: str = "future",
) -> MarketSnapshot:
    return MarketSnapshot(
        orderbook=OrderBookSnapshot(
            bids=[OrderBookLevel(best_bid, 100), OrderBookLevel(best_bid - 1, 200)],
            asks=[OrderBookLevel(best_ask, 100), OrderBookLevel(best_ask + 1, 200)],
        ),
        ticker=TickerSnapshot(mark_price=(best_bid + best_ask) / 2),
        my_order=MyOrderState(price=my_price, amount=10),
        direction=direction,
        target_amount=10,
        elapsed_ms=elapsed_ms,
        timeout_ms=timeout_ms,
        amend_count=amend_count,
        price_limit=price_limit,
        tick_size=tick_size,
        fee_context=FeeContext(
            maker_fee=0.0 if instrument_type == "future" else 0.0003,
            taker_fee=0.0005 if instrument_type == "future" else 0.0003,
            is_post_only=instrument_type == "future",
            instrument_type=instrument_type,
        ),
    )


# ── Action tests ────────────────────────────────────────────────────

def test_action_types():
    assert Action.HOLD.kind == "hold"
    assert Action.CANCEL.kind == "cancel"
    assert Action.MARKET.kind == "market"
    amend = Action.amend(95000)
    assert amend.kind == "amend"
    assert amend.price == 95000


# ── Algorithm registry ──────────────────────────────────────────────

def test_algorithm_registry():
    algos = list_algorithms()
    assert "intent:standard" in algos
    assert "intent:urgent" in algos


def test_get_unknown_algorithm():
    with pytest.raises(ValueError):
        get_algorithm("nonexistent")


def test_legacy_algorithm_name_rejected():
    """Old short names must not resolve — legacy alias table is gone."""
    with pytest.raises(ValueError):
        get_algorithm("tick-chaser")


# ── Fee logic tests ─────────────────────────────────────────────────

def test_classify_instrument():
    assert classify_instrument("BTC-PERPETUAL") == "perpetual"
    assert classify_instrument("BTC-27JUN25") == "future"
    assert classify_instrument("BTC-27JUN25-70000-C") == "option"
    assert classify_instrument("ETH-27JUN25-3000-P") == "option"


def test_fee_context_futures():
    ctx = build_fee_context("BTC-PERPETUAL")
    assert ctx.maker_fee == 0.0
    assert ctx.taker_fee == 0.0005
    assert ctx.is_post_only is True


def test_fee_context_options():
    ctx = build_fee_context("BTC-27JUN25-70000-C")
    assert ctx.maker_fee == 0.0003
    assert ctx.taker_fee == 0.0003
    assert ctx.is_post_only is False


def test_fee_savings():
    ctx = build_fee_context("BTC-PERPETUAL")
    savings = fee_savings_estimate(100000, ctx)
    assert savings["maker_fee"] == 0.0
    assert savings["taker_fee"] == 50.0  # 100000 * 0.0005
    assert savings["savings"] == 50.0


def test_fee_savings_options():
    ctx = build_fee_context("BTC-27JUN25-70000-C")
    savings = fee_savings_estimate(100000, ctx)
    assert savings["savings"] == 0.0  # No savings for options


# ── MarketSnapshot properties ───────────────────────────────────────

def test_snapshot_remaining_time():
    snap = make_snapshot(elapsed_ms=60000, timeout_ms=120000)
    assert snap.remaining_time == 0.5

    snap2 = make_snapshot(elapsed_ms=0, timeout_ms=None)
    assert snap2.remaining_time == 1.0


def test_orderbook_properties():
    snap = make_snapshot(best_bid=94000, best_ask=94010)
    assert snap.orderbook.best_bid == 94000
    assert snap.orderbook.best_ask == 94010
    assert snap.orderbook.mid_price == 94005
    assert snap.orderbook.spread == 10


# ── API integration tests ──────────────────────────────────────────

needs_api = pytest.mark.skipif(
    not os.getenv("DERIBIT_CLIENT_ID"),
    reason="DERIBIT_CLIENT_ID not set",
)

TESTNET_URL = "wss://test.deribit.com/ws/api/v2"


@needs_api
@pytest.mark.asyncio
async def test_smart_order_create_and_cancel():
    """Create a SmartOrder on testnet, then cancel it."""
    from deribit_trading.client import DeribitClient
    from deribit_trading.smart_order.engine import SmartOrderEngine

    client = DeribitClient(TESTNET_URL)
    await client.connect()
    await client.authenticate(
        os.getenv("DERIBIT_CLIENT_ID", ""),
        os.getenv("DERIBIT_CLIENT_SECRET", ""),
    )

    engine = SmartOrderEngine(client)
    await engine.start()

    try:
        config = SmartOrderConfig(
            instrument_name="BTC-PERPETUAL",
            direction="buy",
            amount=10,
            intent="standard",
            t_patience_ms=30_000,
        )
        so = await engine.create_smart_order(config)
        assert so.state in (SmartOrderState.ACTIVE, SmartOrderState.FAILED)

        if so.state == SmartOrderState.ACTIVE:
            assert so.deribit_order_id is not None

            # Cancel it
            cancelled = await engine.cancel_smart_order(so.id)
            assert cancelled is not None
            assert cancelled.state == SmartOrderState.CANCELLED
    finally:
        await engine.stop()
        await client.disconnect()
