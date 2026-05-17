"""Tests for the shared build_smart_order_config constructor."""

from __future__ import annotations

import pytest

from deribit_trading.smart_order.request import (
    OVERRIDE_KEYS,
    build_smart_order_config,
)


def _kwargs(**extra):
    base = dict(instrument_name="BTC-PERPETUAL", direction="buy", amount=1.0)
    base.update(extra)
    return base


def test_default_intent_standard():
    cfg = build_smart_order_config(**_kwargs())
    assert cfg.intent == "standard"
    assert cfg.t_patience_ms == 30_000
    assert cfg.max_cross_levels == 1
    assert cfg.prefer_maker is True


def test_intent_urgent_explicit():
    cfg = build_smart_order_config(**_kwargs(intent="urgent"))
    assert cfg.intent == "urgent"


def test_overrides_apply_to_fields():
    cfg = build_smart_order_config(
        **_kwargs(
            overrides={
                "t_patience_ms": 60_000,
                "max_cross_levels": 3,
                "price_limit_pct": 0.01,
                "prefer_maker": False,
            }
        )
    )
    assert cfg.t_patience_ms == 60_000
    assert cfg.max_cross_levels == 3
    assert cfg.price_limit_pct == 0.01
    assert cfg.prefer_maker is False


def test_unknown_override_key_rejected():
    with pytest.raises(ValueError) as ei:
        build_smart_order_config(**_kwargs(overrides={"patiance": 30_000}))
    msg = str(ei.value)
    assert "patiance" in msg
    # Allowed key set must be listed in sorted order
    for allowed in sorted(OVERRIDE_KEYS):
        assert allowed in msg


def test_unknown_override_multiple_keys_listed():
    with pytest.raises(ValueError) as ei:
        build_smart_order_config(
            **_kwargs(overrides={"foo": 1, "bar": 2, "t_patience_ms": 30_000})
        )
    msg = str(ei.value)
    # Both unknown keys present, sorted
    assert "['bar', 'foo']" in msg


def test_invalid_direction_rejected():
    with pytest.raises(ValueError) as ei:
        build_smart_order_config(
            instrument_name="BTC-PERPETUAL", direction="long", amount=1.0
        )
    assert "direction" in str(ei.value)


def test_invalid_price_limit_pct_propagates_from_post_init():
    with pytest.raises(ValueError) as ei:
        build_smart_order_config(
            **_kwargs(overrides={"price_limit_pct": 0.1})
        )
    assert "price_limit_pct" in str(ei.value)


def test_empty_overrides_dict_ok():
    cfg = build_smart_order_config(**_kwargs(overrides={}))
    assert cfg.intent == "standard"


def test_none_overrides_ok():
    cfg = build_smart_order_config(**_kwargs(overrides=None))
    assert cfg.intent == "standard"
