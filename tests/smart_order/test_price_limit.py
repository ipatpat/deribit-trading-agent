"""Tests for class-aware price_limit checks."""

from __future__ import annotations

import pytest

from deribit_trading.smart_order.price_limit import is_price_limit_breached
from deribit_trading.smart_order.types import (
    FeeContext,
    MarketSnapshot,
    OrderBookSnapshot,
    SmartOrderConfig,
    TickerSnapshot,
)


def _snap(arrival: float, instrument_class: str, tick_size: float, direction: str = "buy") -> MarketSnapshot:
    return MarketSnapshot(
        orderbook=OrderBookSnapshot(bids=[], asks=[]),
        ticker=TickerSnapshot(mark_price=arrival),
        fee_context=FeeContext(maker_fee=0, taker_fee=0.0005),
        arrival_mid=arrival,
        instrument_class=instrument_class,
        tick_size=tick_size,
        direction=direction,
    )


def test_perp_pct_within_limit() -> None:
    snap = _snap(arrival=100_000, instrument_class="perp", tick_size=0.5, direction="buy")
    cfg = SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1, price_limit_pct=0.003)
    # +0.2% movement → within
    assert is_price_limit_breached(snap, target_price=100_200, config=cfg) is False


def test_perp_pct_breach_buy() -> None:
    snap = _snap(arrival=100_000, instrument_class="perp", tick_size=0.5, direction="buy")
    cfg = SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1, price_limit_pct=0.003)
    # +0.4% movement → breach
    assert is_price_limit_breached(snap, target_price=100_400, config=cfg) is True


def test_perp_pct_breach_sell() -> None:
    snap = _snap(arrival=100_000, instrument_class="perp", tick_size=0.5, direction="sell")
    cfg = SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="sell", amount=1, price_limit_pct=0.003)
    # sell at -0.4% → breach
    assert is_price_limit_breached(snap, target_price=99_600, config=cfg) is True


def test_option_ticks_within_limit() -> None:
    snap = _snap(arrival=0.0050, instrument_class="option", tick_size=0.0001, direction="buy")
    cfg = SmartOrderConfig(
        instrument_name="BTC-28JUN26-100000-C", direction="buy", amount=1,
        price_limit_ticks=5,
    )
    # 4 ticks away → within
    assert is_price_limit_breached(snap, target_price=0.0054, config=cfg) is False


def test_option_ticks_breach() -> None:
    snap = _snap(arrival=0.0050, instrument_class="option", tick_size=0.0001, direction="buy")
    cfg = SmartOrderConfig(
        instrument_name="BTC-28JUN26-100000-C", direction="buy", amount=1,
        price_limit_ticks=5,
    )
    # 6 ticks away → breach
    assert is_price_limit_breached(snap, target_price=0.0056, config=cfg) is True


def test_option_iv_lookup_unavailable_falls_back_to_ticks() -> None:
    snap = _snap(arrival=0.0050, instrument_class="option", tick_size=0.0001, direction="buy")
    cfg = SmartOrderConfig(
        instrument_name="BTC-28JUN26-100000-C", direction="buy", amount=1,
        price_limit_ticks=5, price_limit_iv=0.02,
    )
    # iv_lookup=None → IV check skipped, only ticks; 4 ticks → within
    assert is_price_limit_breached(snap, target_price=0.0054, config=cfg, iv_lookup=None) is False


def test_option_iv_breach() -> None:
    snap = _snap(arrival=0.0050, instrument_class="option", tick_size=0.0001, direction="buy")
    cfg = SmartOrderConfig(
        instrument_name="BTC-28JUN26-100000-C", direction="buy", amount=1,
        price_limit_ticks=10,  # ticks limit loose so IV is the binding constraint
        price_limit_iv=0.01,   # ±1 vol
    )
    # iv difference = 0.03 > 0.01 → breach
    iv_lookup = lambda p: 0.55 if p > 0.005 else 0.52
    assert is_price_limit_breached(snap, target_price=0.0058, config=cfg, iv_lookup=iv_lookup) is True


def test_no_arrival_treated_as_unbreachable() -> None:
    """If arrival_mid is unset, no anchor → not breached (graceful)."""
    snap = MarketSnapshot(
        orderbook=OrderBookSnapshot(bids=[], asks=[]),
        ticker=TickerSnapshot(mark_price=100_000),
        fee_context=FeeContext(maker_fee=0, taker_fee=0.0005),
        arrival_mid=0.0,  # unset
        instrument_class="perp",
        tick_size=0.5,
        direction="buy",
    )
    cfg = SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1)
    assert is_price_limit_breached(snap, target_price=999_999, config=cfg) is False


def test_config_validation_pct_out_of_range() -> None:
    with pytest.raises(ValueError, match="price_limit_pct"):
        SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1, price_limit_pct=0.5)
    with pytest.raises(ValueError, match="price_limit_pct"):
        SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1, price_limit_pct=-0.01)


def test_config_validation_ticks_negative() -> None:
    with pytest.raises(ValueError, match="price_limit_ticks"):
        SmartOrderConfig(
            instrument_name="BTC-28JUN26-100000-C", direction="buy", amount=1,
            price_limit_ticks=-1,
        )


def test_config_validation_iv_out_of_range() -> None:
    with pytest.raises(ValueError, match="price_limit_iv"):
        SmartOrderConfig(
            instrument_name="BTC-28JUN26-100000-C", direction="buy", amount=1,
            price_limit_iv=0.5,
        )


def test_config_validation_t_patience_positive() -> None:
    with pytest.raises(ValueError, match="t_patience_ms"):
        SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1, t_patience_ms=0)


def test_config_validation_max_cross_levels() -> None:
    with pytest.raises(ValueError, match="max_cross_levels"):
        SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1, max_cross_levels=0)
