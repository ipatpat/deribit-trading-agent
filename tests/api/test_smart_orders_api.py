"""Tests for the SmartOrders REST request → SmartOrderConfig translation.

We exercise `_build_smart_order_config` directly rather than spinning up the
full FastAPI app — the goal is to cover the intent path, overrides validation,
and rejection of legacy fields.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from deribit_trading.rest_api import SmartOrderRequest, _build_smart_order_config


def _req(**kwargs):
    base = dict(instrument_name="BTC-PERPETUAL", direction="buy", amount=1.0)
    base.update(kwargs)
    return SmartOrderRequest(**base)


# ── Intent path ────────────────────────────────────────────────────


def test_intent_standard_default() -> None:
    """No intent given → defaults to standard."""
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


def test_intent_unknown_override_rejected_as_400() -> None:
    with pytest.raises(HTTPException) as ei:
        _build_smart_order_config(_req(intent="standard", overrides={"bogus_key": 1}))
    assert ei.value.status_code == 400
    assert "bogus_key" in ei.value.detail


def test_intent_invalid_override_value_returns_400() -> None:
    """SmartOrderConfig.__post_init__ ValueError surfaces as 400."""
    with pytest.raises(HTTPException) as ei:
        _build_smart_order_config(
            _req(intent="standard", overrides={"price_limit_pct": 0.5})  # > 0.05 max
        )
    assert ei.value.status_code == 400
    assert "price_limit_pct" in ei.value.detail


# ── Legacy fields rejected at Pydantic layer (extra='forbid') ──────


@pytest.mark.parametrize(
    "field, value",
    [
        ("algorithm", "tick-chaser"),
        ("algo_params", {"offset_ticks": 1}),
        ("patience", 0.5),
        ("price_limit", 70000),
        ("timeout_ms", 60_000),
        ("prefer_maker", False),
    ],
)
def test_legacy_field_rejected(field, value) -> None:
    """Each removed legacy field must trigger a Pydantic validation error."""
    with pytest.raises(ValidationError) as ei:
        SmartOrderRequest(
            instrument_name="BTC-PERPETUAL",
            direction="buy",
            amount=1.0,
            **{field: value},
        )
    assert field in str(ei.value)


def test_invalid_direction_rejected_at_pydantic_layer() -> None:
    with pytest.raises(ValidationError):
        SmartOrderRequest(instrument_name="BTC-PERPETUAL", direction="long", amount=1.0)


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
