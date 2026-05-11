"""Class-aware price-limit checks for SmartOrder.

Perp / future:
    target ≤ arrival_mid * (1 + price_limit_pct)   (buy)
    target ≥ arrival_mid * (1 - price_limit_pct)   (sell)
    Default price_limit_pct = 0.003  (±0.3%)

Option:
    Two constraints (both must hold; either breach triggers CANCEL):
      a) |target − arrival_mid| ≤ price_limit_ticks * tick_size
      b) |IV(target) − IV(arrival_mid)| ≤ price_limit_iv      (skipped if no BS)
    Defaults: price_limit_ticks = 5, price_limit_iv = 0.02

Returns False = within limit (continue trading); True = breach (cancel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import MarketSnapshot, SmartOrderConfig

DEFAULT_PERP_PCT = 0.003
DEFAULT_OPTION_TICKS = 5
DEFAULT_OPTION_IV = 0.02


def is_price_limit_breached(
    snapshot: "MarketSnapshot",
    target_price: float,
    config: "SmartOrderConfig",
    iv_lookup=None,
) -> bool:
    """Check whether `target_price` exceeds the configured price_limit.

    `iv_lookup`: optional callable (price → IV) for option IV-limit; pass None
    to skip the IV check (e.g., when BS pricer is unavailable).
    """
    arrival = snapshot.arrival_mid
    if arrival <= 0:
        # No anchor → cannot enforce; treat as not breached
        return False

    if snapshot.instrument_class == "option":
        ticks_limit = config.price_limit_ticks if config.price_limit_ticks is not None else DEFAULT_OPTION_TICKS
        if abs(target_price - arrival) > ticks_limit * snapshot.tick_size:
            return True
        iv_limit = config.price_limit_iv if config.price_limit_iv is not None else DEFAULT_OPTION_IV
        if iv_lookup is not None and iv_limit is not None:
            try:
                iv_target = iv_lookup(target_price)
                iv_arrival = iv_lookup(arrival)
                if iv_target is not None and iv_arrival is not None:
                    if abs(iv_target - iv_arrival) > iv_limit:
                        return True
            except Exception:
                pass  # BS failure → ticks-only path
        return False

    # perp / future
    pct = config.price_limit_pct if config.price_limit_pct is not None else DEFAULT_PERP_PCT
    if snapshot.direction == "buy":
        return target_price > arrival * (1 + pct)
    return target_price < arrival * (1 - pct)
