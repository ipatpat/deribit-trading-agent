"""Tests for post_only-reject recovery flow.

Covers:
  - Throttle recovery hard cap (5 req/s per SmartOrder)
  - IntentRouter on_post_only_reject behavior in same-snapshot retry budget
"""

from __future__ import annotations

import time

import deribit_trading.algorithms.intent_router  # noqa: F401  # register
from deribit_trading.algorithms.intent_router import StandardIntent
from deribit_trading.smart_order.throttle import AmendThrottle
from deribit_trading.smart_order.types import (
    Action,
    FeeContext,
    MarketSnapshot,
    MyOrderState,
    OrderBookLevel,
    OrderBookSnapshot,
    SmartOrderConfig,
    TickerSnapshot,
)


def _snap(my_level: int = 0, my_price: float = 100_000) -> MarketSnapshot:
    return MarketSnapshot(
        orderbook=OrderBookSnapshot(
            bids=[OrderBookLevel(100_000, 1)],
            asks=[OrderBookLevel(100_001, 1)],
        ),
        ticker=TickerSnapshot(mark_price=100_000.5),
        fee_context=FeeContext(maker_fee=0, taker_fee=0.0005),
        my_order=MyOrderState(price=my_price, amount=1, current_level=my_level),
        direction="buy",
        target_amount=1,
        sigma=0.0,
        tick_size=0.5,
        arrival_mid=100_000.5,
        instrument_class="perp",
    )


# ── Throttle recovery cap ───────────────────────────────────────────


def test_throttle_recovery_hard_cap_per_smart_order() -> None:
    t = AmendThrottle()
    so_id = "so-test"
    # 5 within the cap → all allowed
    for _ in range(5):
        assert t.can_enqueue_recovery(so_id) is True
        t.record_recovery(so_id)
    # 6th in same second → denied
    assert t.can_enqueue_recovery(so_id) is False


def test_throttle_recovery_cap_resets_after_window() -> None:
    t = AmendThrottle()
    so_id = "so-test"
    for _ in range(5):
        t.record_recovery(so_id)
    assert t.can_enqueue_recovery(so_id) is False
    # Force advance the deque manually for test (avoid sleeping 1s)
    t._recovery_history[so_id].clear()
    assert t.can_enqueue_recovery(so_id) is True


def test_throttle_recovery_cap_isolates_per_smart_order() -> None:
    t = AmendThrottle()
    for _ in range(5):
        t.record_recovery("so-A")
    assert t.can_enqueue_recovery("so-A") is False
    # Different SmartOrder still has full budget
    assert t.can_enqueue_recovery("so-B") is True


# ── IntentRouter on_post_only_reject ────────────────────────────────


def test_intent_router_replaces_then_escalates_in_same_snapshot() -> None:
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="standard", t_patience_ms=30_000,
    )
    algo = StandardIntent()
    algo.attach_config(cfg)
    init = _snap(my_level=0, my_price=100_000)
    algo.initial_price(init)

    # Same snapshot id → first reject = retry, second reject = escalate
    snapshot = _snap(my_level=0, my_price=100_000)
    a1 = algo.on_post_only_reject(snapshot)
    assert a1.kind == "amend"
    assert a1.post_only is True

    a2 = algo.on_post_only_reject(snapshot)
    # Second reject in same snapshot escalates → amend at Lv1 mid
    assert a2.kind == "amend"


def test_intent_router_replace_then_new_snapshot_resets_budget() -> None:
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1, intent="standard",
    )
    algo = StandardIntent()
    algo.attach_config(cfg)
    init = _snap(my_level=0)
    algo.initial_price(init)

    snap_a = _snap(my_level=0)
    a1 = algo.on_post_only_reject(snap_a)
    assert a1.kind == "amend"
    # New snapshot (different id) resets budget → retry allowed again
    snap_b = _snap(my_level=0)
    a2 = algo.on_post_only_reject(snap_b)
    assert a2.kind == "amend"
    assert a2.post_only is True


def test_intent_router_reject_at_lv2_escalates_to_ioc() -> None:
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1, intent="standard",
    )
    algo = StandardIntent()
    algo.attach_config(cfg)
    algo.initial_price(_snap(my_level=0))

    snap = _snap(my_level=2)
    # First reject at Lv2 still re-places at Lv2
    a1 = algo.on_post_only_reject(snap)
    assert a1.kind == "amend"
    # Second reject same snapshot → escalate to Lv3 IOC
    a2 = algo.on_post_only_reject(snap)
    assert a2.kind == "ioc"
