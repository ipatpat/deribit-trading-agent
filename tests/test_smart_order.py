"""Tests for the smart order engine.

Local tests: algorithm logic, types, fee logic (no network).
API tests: SmartOrder on testnet (require DERIBIT_CLIENT_ID).
"""

import os

import pytest
import pytest_asyncio

from deribit_trading.smart_order.types import (
    Action,
    FeeContext,
    MarketSnapshot,
    MicroFeatures,
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
    should_use_post_only,
)
from deribit_trading.algorithms import get_algorithm, list_algorithms
import deribit_trading.algorithms.legacy  # noqa: F401  -- registers legacy:* names
from deribit_trading.algorithms.legacy.tick_chaser import TickChaser
from deribit_trading.algorithms.legacy.timed_escalation import TimedEscalation


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
    assert "legacy:tick-chaser" in algos
    assert "legacy:timed-escalation" in algos


def test_get_algorithm():
    algo = get_algorithm("legacy:tick-chaser", {"offset_ticks": 1})
    assert algo.name == "legacy:tick-chaser"


def test_legacy_alias_warns_and_resolves():
    """Old short name 'tick-chaser' resolves to legacy:* with DeprecationWarning."""
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        algo = get_algorithm("tick-chaser", {"offset_ticks": 1})
    assert algo.name == "legacy:tick-chaser"
    assert any(issubclass(c.category, DeprecationWarning) for c in caught)


def test_get_unknown_algorithm():
    with pytest.raises(ValueError):
        get_algorithm("nonexistent")


# ── TickChaser tests ────────────────────────────────────────────────

def test_tick_chaser_initial_price():
    algo = TickChaser(offset_ticks=0)
    snap = make_snapshot(best_bid=94000)
    assert algo.initial_price(snap) == 94000


def test_tick_chaser_initial_price_with_offset():
    algo = TickChaser(offset_ticks=2)
    snap = make_snapshot(best_bid=94000, tick_size=0.5)
    assert algo.initial_price(snap) == 94001.0  # 94000 + 2*0.5


def test_tick_chaser_hold_when_close():
    algo = TickChaser(min_ticks=2)
    snap = make_snapshot(best_bid=94000, my_price=94000)
    assert algo.on_update(snap) == Action.HOLD


def test_tick_chaser_amend_when_moved():
    algo = TickChaser(min_ticks=2)
    # best_bid moved 5 ticks away from my order
    snap = make_snapshot(best_bid=94005, my_price=94000, tick_size=1)
    action = algo.on_update(snap)
    assert action.kind == "amend"
    assert action.price == 94005


def test_tick_chaser_cancel_on_price_limit():
    algo = TickChaser()
    snap = make_snapshot(best_bid=95000, my_price=94000, price_limit=94500)
    action = algo.on_update(snap)
    assert action.kind == "cancel"


def test_tick_chaser_timeout():
    algo = TickChaser()
    snap = make_snapshot(elapsed_ms=130000, timeout_ms=120000)
    assert algo.on_update(snap) == Action.MARKET


# ── TimedEscalation tests ──────────────────────────────────────────

def test_timed_escalation_patience_phase():
    algo = TimedEscalation(patience_ms=30000)
    snap = make_snapshot(elapsed_ms=10000, best_bid=94000, my_price=94000)
    assert algo.on_update(snap) == Action.HOLD  # in patience, no change


def test_timed_escalation_escalate():
    algo = TimedEscalation(patience_ms=10000, step_interval_ms=5000, step_ticks=1)
    # Past patience, one step interval elapsed
    snap = make_snapshot(elapsed_ms=16000, best_bid=94000, my_price=94000, tick_size=0.5)
    action = algo.on_update(snap)
    assert action.kind == "amend"
    assert action.price == 94000.5  # +1 tick for buy


def test_timed_escalation_timeout_market():
    algo = TimedEscalation(timeout_action="market")
    snap = make_snapshot(elapsed_ms=130000, timeout_ms=120000)
    assert algo.on_update(snap) == Action.MARKET


def test_timed_escalation_timeout_cancel():
    algo = TimedEscalation(timeout_action="cancel")
    snap = make_snapshot(elapsed_ms=130000, timeout_ms=120000)
    assert algo.on_update(snap) == Action.CANCEL


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
            algorithm="tick-chaser",
            algo_params={"offset_ticks": -5},  # very low to ensure post_only
            timeout_ms=30000,
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
