"""Shared SmartOrderConfig constructor for REST and MCP entry points.

Pure function. Does not import FastAPI / Pydantic / Starlette so it can be
called from any layer. Both `rest_api._build_smart_order_config` and the MCP
`smart_order` handler delegate here; future entry points should do the same.
"""

from __future__ import annotations

from typing import Any, Literal

from .types import SmartOrderConfig

Intent = Literal["standard", "urgent"]

OVERRIDE_KEYS = frozenset(
    {
        "t_patience_ms",
        "max_cross_levels",
        "price_limit_pct",
        "price_limit_ticks",
        "price_limit_iv",
        "prefer_maker",
    }
)


def build_smart_order_config(
    *,
    instrument_name: str,
    direction: str,
    amount: float,
    intent: Intent = "standard",
    overrides: dict[str, Any] | None = None,
) -> SmartOrderConfig:
    """Build a SmartOrderConfig from intent + overrides.

    Raises ValueError on:
      - direction not in {"buy", "sell"}
      - overrides containing keys outside OVERRIDE_KEYS
      - any constraint violation from SmartOrderConfig.__post_init__
        (e.g. price_limit_pct out of range)
    """
    if direction not in ("buy", "sell"):
        raise ValueError(
            f"direction must be 'buy' or 'sell', got {direction!r}"
        )

    overrides = overrides or {}
    unknown = set(overrides) - OVERRIDE_KEYS
    if unknown:
        raise ValueError(
            f"Unknown overrides keys: {sorted(unknown)}. "
            f"Allowed: {sorted(OVERRIDE_KEYS)}"
        )

    return SmartOrderConfig(
        instrument_name=instrument_name,
        direction=direction,
        amount=amount,
        intent=intent,
        **overrides,
    )
