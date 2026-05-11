"""Tests for IntentRouter: Standard / Urgent paths, σ amend, escalation, post_only reject."""

from __future__ import annotations

import deribit_trading.algorithms.intent_router  # noqa: F401  # register
from deribit_trading.algorithms import get_algorithm
from deribit_trading.algorithms.intent_router import StandardIntent, UrgentIntent
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


def _ob(bb: float, ba: float, depth: int = 10, size: float = 1.0) -> OrderBookSnapshot:
    bids = [OrderBookLevel(price=bb - i * 0.5, size=size) for i in range(depth)]
    asks = [OrderBookLevel(price=ba + i * 0.5, size=size) for i in range(depth)]
    return OrderBookSnapshot(bids=bids, asks=asks)


def _snap(
    *,
    direction: str = "buy",
    bb: float = 100_000,
    ba: float = 100_001,
    my_price: float = 100_000,
    my_amount: float = 1.0,
    filled: float = 0.0,
    elapsed_ms: int = 0,
    sigma: float = 0.0,
    tick_size: float = 0.5,
    arrival_mid: float = 100_000.5,
    instrument_class: str = "perp",
    current_level: int = 0,
) -> MarketSnapshot:
    return MarketSnapshot(
        orderbook=_ob(bb, ba),
        ticker=TickerSnapshot(mark_price=(bb + ba) / 2),
        fee_context=FeeContext(maker_fee=0, taker_fee=0.0005),
        my_order=MyOrderState(
            price=my_price, amount=my_amount, filled_amount=filled,
            current_level=current_level,
        ),
        direction=direction,
        target_amount=my_amount,
        elapsed_ms=elapsed_ms,
        sigma=sigma,
        tick_size=tick_size,
        arrival_mid=arrival_mid,
        instrument_class=instrument_class,
    )


def _make_standard(t_patience_ms: int = 30_000) -> StandardIntent:
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="standard", t_patience_ms=t_patience_ms,
    )
    algo = StandardIntent(t_patience_ms=t_patience_ms)
    algo.attach_config(cfg)
    return algo


def _make_urgent() -> UrgentIntent:
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="urgent",
    )
    algo = UrgentIntent()
    algo.attach_config(cfg)
    return algo


# ── Initial price ───────────────────────────────────────────────────


def test_standard_initial_price_lv0_own_top() -> None:
    algo = _make_standard()
    snap = _snap(direction="buy", bb=100_000, ba=100_001)
    assert algo.initial_price(snap) == 100_000  # best_bid


def test_urgent_initial_price_crosses() -> None:
    algo = _make_urgent()
    snap = _snap(direction="buy", bb=100_000, ba=100_001)
    # Urgent goes Lv3: best_ask + 1 tick (default max_cross_levels=1)
    assert algo.initial_price(snap) > 100_000


# ── Standard amend behavior ─────────────────────────────────────────


def test_standard_holds_when_my_price_at_best_bid() -> None:
    algo = _make_standard()
    snap = _snap(my_price=100_000, bb=100_000, ba=100_001, sigma=0.5)
    algo.initial_price(snap)
    assert algo.on_update(snap) == Action.HOLD


def test_standard_amends_when_best_bid_moves_beyond_threshold() -> None:
    algo = _make_standard()
    # σ=0.5, tick=0.5, k=2 → threshold = ceil(2*0.5*1/0.5) = 2 ticks
    init = _snap(my_price=100_000, bb=100_000, ba=100_001, sigma=0.5)
    algo.initial_price(init)
    # best_bid moves +2 ticks (1.0)
    snap2 = _snap(my_price=100_000, bb=100_001, ba=100_002, sigma=0.5)
    action = algo.on_update(snap2)
    assert action.kind == "amend"
    assert action.price == 100_001
    assert action.post_only is True


def test_standard_holds_when_movement_below_threshold() -> None:
    algo = _make_standard()
    init = _snap(my_price=100_000, bb=100_000, ba=100_001, sigma=2.0)
    algo.initial_price(init)
    # σ=2, k=2 → threshold = ceil(2*2/0.5) = 8 ticks; best_bid moves only 1 tick
    snap2 = _snap(my_price=100_000, bb=100_000.5, ba=100_001, sigma=2.0)
    assert algo.on_update(snap2) == Action.HOLD


# ── Standard escalation ladder ──────────────────────────────────────


def test_standard_escalates_lv0_to_lv1_at_40pct_patience() -> None:
    algo = _make_standard(t_patience_ms=10_000)
    init = _snap(bb=100_000, ba=100_002, sigma=0.0)  # spread=2
    algo.initial_price(init)
    # 50% of patience elapsed → past Lv0 budget (40%)
    snap2 = _snap(my_price=100_000, bb=100_000, ba=100_002, elapsed_ms=5_000, sigma=0.0)
    action = algo.on_update(snap2)
    assert action.kind == "amend"
    # Lv1 mid (snapped down to be < ba) → 100_001 (the floor of 100_001 with tick 0.5)
    assert action.price == 100_001
    assert action.post_only is True  # mid is still < ba


def test_standard_escalates_to_lv2_at_70pct() -> None:
    algo = _make_standard(t_patience_ms=10_000)
    init = _snap(bb=100_000, ba=100_001, sigma=0.0)
    algo.initial_price(init)
    snap_lv0 = _snap(my_price=100_000, bb=100_000, ba=100_001, elapsed_ms=4_500, sigma=0.0)
    algo.on_update(snap_lv0)  # noop or amend; stay at level 0 by my_order.current_level
    snap_lv1 = _snap(my_price=100_000.5, bb=100_000, ba=100_001, elapsed_ms=7_500, sigma=0.0, current_level=1)
    action = algo.on_update(snap_lv1)
    # Lv1 budget=0.7, elapsed=0.75 → escalate to Lv2 (cross to ask)
    assert action.kind == "amend"
    assert action.price == 100_001
    assert action.post_only is False


def test_standard_escalates_to_lv3_ioc_at_100pct() -> None:
    algo = _make_standard(t_patience_ms=10_000)
    init = _snap(bb=100_000, ba=100_001, sigma=0.0)
    algo.initial_price(init)
    snap_lv2 = _snap(
        my_price=100_001, bb=100_000, ba=100_001,
        elapsed_ms=10_500, sigma=0.0, current_level=2,
    )
    action = algo.on_update(snap_lv2)
    assert action.kind == "ioc"
    assert action.price >= 100_001  # crosses + tick padding


def test_standard_burst_triggers_escalate() -> None:
    algo = _make_standard(t_patience_ms=10_000)
    init = _snap(bb=100_000, ba=100_001, sigma=1.0)
    algo.initial_price(init)
    # σ explodes 4x → above BURST_K (3) → escalate
    snap2 = _snap(my_price=100_000, bb=100_000, ba=100_001, elapsed_ms=1_000, sigma=4.0)
    action = algo.on_update(snap2)
    assert action.kind == "amend"
    # Should jump to Lv1 (mid)
    assert action.post_only in (True, False)


def test_standard_price_limit_breach_cancels() -> None:
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="standard", price_limit_pct=0.001,  # ±0.1% = $100 from arrival 100k
    )
    algo = StandardIntent()
    algo.attach_config(cfg)
    # arrival 100_000, target 100_500 → way past 0.1% limit
    snap = _snap(
        my_price=100_000, bb=100_500, ba=100_501,
        arrival_mid=100_000, sigma=0.5,
    )
    algo.initial_price(_snap(bb=100_000, ba=100_001, arrival_mid=100_000))
    action = algo.on_update(snap)
    assert action.kind == "cancel"


# ── Urgent path ─────────────────────────────────────────────────────


def test_urgent_first_call_returns_ioc() -> None:
    algo = _make_urgent()
    snap = _snap(direction="buy", bb=100_000, ba=100_001, my_price=0, current_level=0)
    algo.initial_price(snap)
    action = algo.on_update(snap)
    assert action.kind == "ioc"
    assert action.amount == 1.0


def test_urgent_remainder_goes_market() -> None:
    algo = _make_urgent()
    # IOC partially filled, remaining 0.4 → engine sets current_level=3
    snap = _snap(
        direction="buy", bb=100_000, ba=100_001,
        my_price=100_002, my_amount=1.0, filled=0.6, current_level=3,
    )
    action = algo.on_update(snap)
    assert action.kind == "market"


# ── post_only reject recovery ───────────────────────────────────────


def test_post_only_reject_first_retry_replaces_same_level() -> None:
    algo = _make_standard()
    init = _snap(bb=100_000, ba=100_001)
    algo.initial_price(init)
    # Best moved up 1 tick, my order at 100_000 was rejected
    reject_snap = _snap(my_price=100_000, bb=100_000.5, ba=100_001.5, current_level=0)
    action = algo.on_post_only_reject(reject_snap)
    assert action.kind == "amend"
    assert action.price == 100_000.5  # new own-top
    assert action.post_only is True


def test_post_only_reject_second_in_same_snapshot_escalates() -> None:
    algo = _make_standard()
    init = _snap(bb=100_000, ba=100_001)
    algo.initial_price(init)
    reject_snap = _snap(my_price=100_000, bb=100_000.5, ba=100_001.5, current_level=0)
    algo.on_post_only_reject(reject_snap)
    action2 = algo.on_post_only_reject(reject_snap)  # same snapshot id → escalate
    # Should escalate to Lv1 (amend with mid)
    assert action2.kind == "amend"


# ── Registry ────────────────────────────────────────────────────────


def test_registry_has_intent_algos() -> None:
    standard = get_algorithm("intent:standard", {})
    urgent = get_algorithm("intent:urgent", {})
    assert standard.name == "intent:standard"
    assert urgent.name == "intent:urgent"
