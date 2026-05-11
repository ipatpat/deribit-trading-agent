"""Tests for the SmartOrders REST request → SmartOrderConfig translation.

We exercise `_build_smart_order_config` directly rather than spinning up the
full FastAPI app — the goal is to cover intent path, legacy fallbacks, and
overrides validation.
"""

from __future__ import annotations

import warnings

import pytest
from fastapi import HTTPException

from deribit_trading.rest_api import SmartOrderRequest, _build_smart_order_config


def _req(**kwargs):
    base = dict(instrument_name="BTC-PERPETUAL", direction="buy", amount=1.0)
    base.update(kwargs)
    return SmartOrderRequest(**base)


# ── Intent path ────────────────────────────────────────────────────


def test_intent_standard_default() -> None:
    """No intent + no legacy fields → defaults to standard intent."""
    cfg = _build_smart_order_config(_req())
    assert cfg.intent == "standard"
    assert cfg.t_patience_ms == 30_000  # default


def test_intent_urgent_explicit() -> None:
    cfg = _build_smart_order_config(_req(intent="urgent"))
    assert cfg.intent == "urgent"


def test_intent_with_overrides() -> None:
    cfg = _build_smart_order_config(
        _req(intent="standard", overrides={"t_patience_ms": 60_000, "max_cross_levels": 2})
    )
    assert cfg.intent == "standard"
    assert cfg.t_patience_ms == 60_000
    assert cfg.max_cross_levels == 2


def test_intent_overrides_with_price_limit_ticks() -> None:
    cfg = _build_smart_order_config(
        _req(intent="standard", overrides={"price_limit_ticks": 10})
    )
    assert cfg.price_limit_ticks == 10


def test_intent_unknown_override_rejected() -> None:
    with pytest.raises(HTTPException) as ei:
        _build_smart_order_config(_req(intent="standard", overrides={"bogus_key": 1}))
    assert ei.value.status_code == 400
    assert "bogus_key" in ei.value.detail


def test_intent_invalid_override_value_propagates() -> None:
    """SmartOrderConfig.__post_init__ ValueError surfaces as 400."""
    with pytest.raises(ValueError):
        _build_smart_order_config(
            _req(intent="standard", overrides={"price_limit_pct": 0.5})  # > 0.05 max
        )


# ── Legacy path ────────────────────────────────────────────────────


def test_legacy_algorithm_field_warns_and_routes() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = _build_smart_order_config(
            _req(algorithm="tick-chaser", algo_params={"offset_ticks": 1})
        )
    assert cfg.algorithm == "tick-chaser"
    assert cfg.algo_params == {"offset_ticks": 1}
    assert any(issubclass(c.category, DeprecationWarning) for c in caught)


def test_legacy_patience_routes_to_from_legacy_urgent() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = _build_smart_order_config(_req(patience=0.1))
    assert cfg.intent == "urgent"  # patience < 0.3 → urgent
    assert any(issubclass(c.category, DeprecationWarning) for c in caught)


def test_legacy_patience_routes_to_from_legacy_standard() -> None:
    cfg = _build_smart_order_config(_req(patience=0.5))
    assert cfg.intent == "standard"


# ── Response shape ─────────────────────────────────────────────────


def test_to_dict_includes_required_response_fields() -> None:
    """7.3: response must include current_level, post_only_reject_count, elapsed_ms."""
    from deribit_trading.smart_order.engine import SmartOrder
    from deribit_trading.smart_order.types import SmartOrderConfig

    cfg = SmartOrderConfig(instrument_name="BTC-PERPETUAL", direction="buy", amount=1.0)
    so = SmartOrder(
        id="so-1",
        config=cfg,
        algorithm=type("A", (), {"name": "intent:standard"})(),  # noqa: ignore
        fee_context=type("F", (), {"is_post_only": True})(),
    )
    d = so.to_dict()
    for field in ("current_level", "post_only_reject_count", "elapsed_ms", "intent"):
        assert field in d, f"missing field: {field}"
