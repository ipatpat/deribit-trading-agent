"""Tests for SigmaTracker: rolling stdev, EWMA, clamps, classifier."""

from __future__ import annotations

import math

from deribit_trading.smart_order.sigma import (
    PROFILES,
    SigmaProfile,
    SigmaTracker,
    classify_instrument,
)


def test_classifier_identifies_classes() -> None:
    assert classify_instrument("BTC-PERPETUAL") == "perp"
    assert classify_instrument("ETH-PERPETUAL") == "perp"
    assert classify_instrument("BTC-28JUN26") == "future"
    assert classify_instrument("BTC-28JUN26-75000-C") == "option"
    assert classify_instrument("BTC-28JUN26-75000-P") == "option"


def test_sigma_returns_zero_with_few_samples() -> None:
    t = SigmaTracker(instrument_class="perp")
    assert t.sigma == 0.0
    t.record_mid(100.0, ts=0)
    assert t.sigma == 0.0  # only 1 sample
    t.record_mid(100.5, ts=1)
    assert t.sigma == 0.0  # only 2 samples


def test_sigma_stable_when_mid_unchanged() -> None:
    t = SigmaTracker(instrument_class="perp")
    for i in range(20):
        t.record_mid(100.0, ts=float(i))
    assert t.sigma == 0.0  # zero variance


def test_sigma_picks_up_movement() -> None:
    t = SigmaTracker(instrument_class="perp")
    # mid moves +1, +1, +1, ... per second
    for i in range(20):
        t.record_mid(100.0 + i, ts=float(i))
    # increments are all +1 → variance = 0 → σ = 0
    assert t.sigma == 0.0

    t2 = SigmaTracker(instrument_class="perp")
    # mid alternates +2, -2, +2, -2 → increments = 2,-2,2,-2,...
    # increments mean 0, var = 4, stdev = 2
    base = 100.0
    for i in range(30):
        delta = 2.0 if i % 2 == 0 else -2.0
        t2.record_mid(base + delta, ts=float(i))
        base += delta
    assert t2.sigma > 0
    # Should be roughly 2 (with EWMA smoothing)
    assert 1.5 < t2.sigma < 2.5


def test_sigma_window_truncation() -> None:
    """Old samples outside window must be evicted."""
    profile = SigmaProfile(window_seconds=10, sigma_min=0, sigma_max=1e9)
    t = SigmaTracker(instrument_class="perp", profile=profile)
    # samples spread over 30 seconds
    for i in range(30):
        t.record_mid(100.0 + i, ts=float(i))
    # Window of 10s + final ts=29 → should retain ts in [19, 29]
    assert t.sample_count <= 11


def test_sigma_clamp_min_max() -> None:
    profile = SigmaProfile(window_seconds=300, sigma_min=5.0, sigma_max=10.0)
    t = SigmaTracker(instrument_class="perp", profile=profile)
    # Stable mid → raw σ = 0, but min clamps to 5.0
    for i in range(20):
        t.record_mid(100.0, ts=float(i))
    assert t.sigma == 5.0  # clamped to min


def test_sigma_ewma_smoothing() -> None:
    """A single spike should not dominate σ; EWMA must dampen it."""
    t = SigmaTracker(instrument_class="perp")
    # 100 stable samples
    for i in range(100):
        t.record_mid(100.0, ts=float(i))
    sigma_before = t.sigma  # 0

    # one giant jump
    t.record_mid(200.0, ts=100.0)
    sigma_after = t.sigma

    # EWMA(α=0.3): new_sigma = 0.3 * raw + 0.7 * prev = 0.3 * raw
    # raw includes one big increment in the window, so σ rises but is dampened.
    raw_estimate = 100.0  # a single 100-unit jump in a 100-sample window
    # With α=0.3, smoothed should be well under raw
    assert sigma_after < raw_estimate * 0.5


def test_default_profiles_exist() -> None:
    assert "perp" in PROFILES
    assert "option" in PROFILES
    assert PROFILES["perp"].window_seconds == 5 * 60
    assert PROFILES["option"].window_seconds == 30 * 60


def test_amend_threshold_ticks_via_snapshot() -> None:
    """MarketSnapshot.amend_threshold_ticks computes σ-based tick threshold."""
    from deribit_trading.smart_order.types import (
        FeeContext,
        MarketSnapshot,
        OrderBookSnapshot,
        TickerSnapshot,
    )

    ob = OrderBookSnapshot(bids=[], asks=[])
    ticker = TickerSnapshot(mark_price=100.0)
    fc = FeeContext(maker_fee=0, taker_fee=0.0005)

    # σ = 1.0, tick_size = 0.5, k=2.0 → threshold = ceil(2*1*1/0.5) = 4
    snap = MarketSnapshot(
        orderbook=ob, ticker=ticker, fee_context=fc,
        sigma=1.0, tick_size=0.5, instrument_class="perp",
    )
    assert snap.amend_threshold_ticks() == 4

    # σ = 0 → falls back to K_min = 1
    snap_zero = MarketSnapshot(
        orderbook=ob, ticker=ticker, fee_context=fc,
        sigma=0.0, tick_size=0.5, instrument_class="perp",
    )
    assert snap_zero.amend_threshold_ticks() == 1

    # Option with k=1, σ=0.0001, tick_size=0.0001 → ceil(1*0.0001/0.0001)=1
    snap_opt = MarketSnapshot(
        orderbook=ob, ticker=ticker, fee_context=fc,
        sigma=0.0001, tick_size=0.0001, instrument_class="option",
    )
    assert snap_opt.amend_threshold_ticks() == 1
