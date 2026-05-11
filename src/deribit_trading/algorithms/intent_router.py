"""IntentRouter: routes Standard / Urgent intents through Lv0-Lv4 escalation.

Standard:  Lv0 own-top → Lv1 mid → Lv2 opposite-top → Lv3 IOC → Lv4 market
Urgent:    Lv3 IOC → Lv4 market

post_only is true at Lv0/Lv1 (with Lv1→false if mid would cross), false at Lv2+.

Algorithm decisions live here; engine handles I/O. on_update() returns Action;
on_post_only_reject() is the recovery path when Deribit rejects with code 10041.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from ..smart_order.price_limit import is_price_limit_breached
from ..smart_order.types import Action, MarketSnapshot, SmartOrderConfig
from . import register_algorithm

Side = Literal["buy", "sell"]

# Burst threshold multiplier: σ * BURST_K → escalate
BURST_K = 3.0

# Per-level patience budgets as fractions of t_patience_ms
LEVEL_BUDGETS: dict[int, float] = {
    0: 0.4,   # Lv0 → Lv1 at 40% of patience
    1: 0.7,   # Lv1 → Lv2 at 70%
    2: 1.0,   # Lv2 → Lv3 at 100%
    # Lv3 IOC fires once; remaining (if any) → Lv4
}


@dataclass
class IntentRouter:
    """Placement algorithm that escalates from maker-friendly Lv0 to market Lv4."""

    name: str = "intent:standard"  # default; urgent variant overrides via subclass

    intent: str = "standard"
    t_patience_ms: int = 30_000
    max_cross_levels: int = 1
    config: SmartOrderConfig | None = None  # injected by engine

    # Per-snapshot reject tracking (cleared each new snapshot)
    _last_snapshot_id: int = field(default=-1, init=False)
    _post_only_retries_in_snapshot: int = field(default=0, init=False)

    # Cached burst σ baseline (updated when level transitions)
    _baseline_sigma: float = field(default=0.0, init=False)

    def initial_price(self, snapshot: MarketSnapshot) -> float:
        """Compute the price for the initial order placement."""
        # Snapshot σ baseline at start
        self._baseline_sigma = snapshot.sigma

        if self.intent == "urgent":
            # Urgent starts at Lv3 (IOC), but engine needs an initial limit price
            # for the IOC sweep. We return the cross-N-levels price.
            price, _ = self._level_price(level=3, snapshot=snapshot)
            return price
        # Standard starts at Lv0
        price, _ = self._level_price(level=0, snapshot=snapshot)
        return price

    def on_update(self, snapshot: MarketSnapshot) -> Action:
        """Main decision loop: σ-based amend, escalation, price_limit check."""
        # Reset per-snapshot counters
        snapshot_id = id(snapshot)
        if snapshot_id != self._last_snapshot_id:
            self._last_snapshot_id = snapshot_id
            self._post_only_retries_in_snapshot = 0

        my = snapshot.my_order
        level = my.current_level

        # Urgent doesn't loop on amend; it fires once at Lv3 then escalates to Lv4
        if self.intent == "urgent":
            if level >= 4:
                return Action.HOLD  # market already fired
            if level == 3:
                # If IOC partially filled, remaining_amount > 0 → escalate to Lv4
                if snapshot.remaining_amount > 0:
                    return Action.market()
                return Action.HOLD
            # Initial: fire IOC
            target, _ = self._level_price(level=3, snapshot=snapshot)
            return Action.ioc(target, snapshot.remaining_amount)

        # Standard path
        return self._standard_decide(snapshot, level)

    def _standard_decide(self, snapshot: MarketSnapshot, level: int) -> Action:
        my = snapshot.my_order
        target, post_only = self._level_price(level=level, snapshot=snapshot)

        # Price-limit terminal protection (any level)
        if self.config and is_price_limit_breached(snapshot, target, self.config):
            return Action.cancel()

        # Time-based escalation
        elapsed_frac = snapshot.elapsed_ms / max(self.t_patience_ms, 1)
        if level <= 2 and elapsed_frac >= LEVEL_BUDGETS[level]:
            return self._escalate(level, snapshot)

        # Burst-based escalation: σ has tripled since baseline
        if (
            level <= 2
            and self._baseline_sigma > 0
            and snapshot.sigma > self._baseline_sigma * BURST_K
        ):
            return self._escalate(level, snapshot)

        # σ-based amend: if target moved beyond threshold ticks, amend
        if level <= 2:
            diff_ticks = abs(target - my.price) / max(snapshot.tick_size, 1e-9)
            threshold = snapshot.amend_threshold_ticks()
            if diff_ticks >= threshold and target != my.price:
                return Action.amend(target, post_only=post_only)

        return Action.HOLD

    def _escalate(self, current_level: int, snapshot: MarketSnapshot) -> Action:
        next_level = current_level + 1
        # Lv3 IOC
        if next_level == 3:
            target, _ = self._level_price(level=3, snapshot=snapshot)
            # Verify still within price_limit before crossing
            if self.config and is_price_limit_breached(snapshot, target, self.config):
                return Action.cancel()
            return Action.ioc(target, snapshot.remaining_amount)
        # Lv4 market
        if next_level >= 4:
            return Action.market()

        # Lv1, Lv2: amend with new level price + post_only flag flip
        target, post_only = self._level_price(level=next_level, snapshot=snapshot)
        if self.config and is_price_limit_breached(snapshot, target, self.config):
            return Action.cancel()
        # Reset σ baseline on each level transition
        self._baseline_sigma = snapshot.sigma
        return Action.amend(target, post_only=post_only)

    def _level_price(self, level: int, snapshot: MarketSnapshot) -> tuple[float, bool]:
        """Compute (target_price, post_only) for the given escalation level."""
        side: Side = "buy" if snapshot.direction == "buy" else "sell"
        ob = snapshot.orderbook
        bb, ba = ob.best_bid, ob.best_ask
        tick = max(snapshot.tick_size, 1e-9)

        if level == 0:
            # Own-top
            price = bb if side == "buy" else ba
            return self._snap_to_tick(price, tick), True

        if level == 1:
            # Mid, snapped favorably (buyer rounds down to stay maker; seller rounds up)
            mid = (bb + ba) / 2 if (bb and ba) else (bb or ba)
            if side == "buy":
                # Round down to nearest tick to remain ≤ best_ask
                snapped = math.floor(mid / tick) * tick
                # If we'd accidentally meet best_ask, fall back to bb + 1 tick
                if snapped >= ba and ba > 0:
                    snapped = ba - tick
                # post_only stays true if our price < ba
                post_only = snapped < ba if ba > 0 else True
            else:
                snapped = math.ceil(mid / tick) * tick
                if snapped <= bb and bb > 0:
                    snapped = bb + tick
                post_only = snapped > bb if bb > 0 else True
            return snapped, post_only

        if level == 2:
            # Opposite-top: cross to take liquidity (Lv2 is still a limit, not IOC)
            price = ba if side == "buy" else bb
            return self._snap_to_tick(price, tick), False

        if level == 3:
            # IOC sweep up to max_cross_levels deep into the opposite book
            depth = self.max_cross_levels
            if side == "buy":
                if len(ob.asks) >= depth:
                    price = ob.asks[depth - 1].price
                else:
                    price = ba
                # Pad N ticks above for safety
                price += tick * 1
            else:
                if len(ob.bids) >= depth:
                    price = ob.bids[depth - 1].price
                else:
                    price = bb
                price -= tick * 1
            return self._snap_to_tick(price, tick), False

        # Lv4 market: no limit price
        return 0.0, False

    @staticmethod
    def _snap_to_tick(price: float, tick: float) -> float:
        return round(price / tick) * tick

    def on_post_only_reject(self, snapshot: MarketSnapshot) -> Action:
        """Recovery path when Deribit rejects post_only with error 10041."""
        snapshot_id = id(snapshot)
        if snapshot_id != self._last_snapshot_id:
            self._last_snapshot_id = snapshot_id
            self._post_only_retries_in_snapshot = 0

        my = snapshot.my_order
        level = my.current_level

        # Same-snapshot retry budget = 1
        if self._post_only_retries_in_snapshot >= 1:
            return self._escalate(level, snapshot)
        self._post_only_retries_in_snapshot += 1

        # Re-place at same level using latest snapshot
        target, post_only = self._level_price(level=level, snapshot=snapshot)
        if self.config and is_price_limit_breached(snapshot, target, self.config):
            return Action.cancel()
        return Action.amend(target, post_only=post_only)

    def on_fill(self, fill_price: float, fill_amount: float) -> None:
        """Called by engine on (partial) fill. No internal state change needed
        beyond what engine tracks; can be extended for analytics later."""
        pass


@register_algorithm
class StandardIntent(IntentRouter):
    name = "intent:standard"

    def __init__(self, t_patience_ms: int = 30_000, max_cross_levels: int = 1, **kwargs) -> None:
        super().__init__(
            name="intent:standard",
            intent="standard",
            t_patience_ms=t_patience_ms,
            max_cross_levels=max_cross_levels,
        )
        # config is injected by engine via attach_config()

    def attach_config(self, config: SmartOrderConfig) -> None:
        self.config = config


@register_algorithm
class UrgentIntent(IntentRouter):
    name = "intent:urgent"

    def __init__(self, t_patience_ms: int = 30_000, max_cross_levels: int = 1, **kwargs) -> None:
        super().__init__(
            name="intent:urgent",
            intent="urgent",
            t_patience_ms=t_patience_ms,
            max_cross_levels=max_cross_levels,
        )

    def attach_config(self, config: SmartOrderConfig) -> None:
        self.config = config
