"""Core types for the smart order engine.

MarketSnapshot is the sole input to placement algorithms.
Action is the sole output. This boundary keeps algorithms pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


# ── Action ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Action:
    """Decision output from a placement algorithm.

    Variants:
      - HOLD                        : do nothing
      - place(price, post_only)     : initial placement or re-place after reject
      - amend(price, post_only)     : modify existing order's price (and post_only flag)
      - ioc(price, amount)          : immediate-or-cancel sweep (Lv3)
      - cancel()                    : terminate
      - market()                    : convert remaining to market (Lv4)
    """

    kind: str  # "hold" | "place" | "amend" | "ioc" | "cancel" | "market"
    price: float | None = None
    post_only: bool = False
    amount: float | None = None  # only for ioc

    HOLD: Action = None  # type: ignore[assignment]  # set below

    @classmethod
    def place(cls, price: float, post_only: bool = True) -> Action:
        return cls(kind="place", price=price, post_only=post_only)

    @classmethod
    def amend(cls, new_price: float, post_only: bool = True) -> Action:
        return cls(kind="amend", price=new_price, post_only=post_only)

    @classmethod
    def ioc(cls, price: float, amount: float) -> Action:
        return cls(kind="ioc", price=price, amount=amount, post_only=False)

    @classmethod
    def cancel(cls) -> Action:
        return cls(kind="cancel")

    @classmethod
    def market(cls) -> Action:
        return cls(kind="market")


# Singleton HOLD (immutable, no parameters)
Action.HOLD = Action(kind="hold")

# Backwards-compat sentinels (deprecated; use Action.cancel() / Action.market())
Action.CANCEL = Action(kind="cancel")  # type: ignore[attr-defined]
Action.MARKET = Action(kind="market")  # type: ignore[attr-defined]


# ── SmartOrder state ────────────────────────────────────────────────


class SmartOrderState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ESCALATING = "escalating"  # Transient: cancel→place between escalation levels
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    MARKET_FILLED = "market_filled"
    FAILED = "failed"


# ── MarketSnapshot sub-components ───────────────────────────────────


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBookSnapshot:
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return self.best_bid or self.best_ask

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid if self.best_bid and self.best_ask else 0.0


@dataclass(frozen=True)
class TickerSnapshot:
    mark_price: float
    index_price: float | None = None
    last_price: float | None = None
    funding_rate: float | None = None
    implied_vol: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


@dataclass(frozen=True)
class MyOrderState:
    price: float
    amount: float
    filled_amount: float = 0.0
    state: str = "open"  # open, filled, cancelled
    post_only_rejected: bool = False
    post_only_reject_count: int = 0
    current_level: int = 0  # 0-4: Lv0 own-top, Lv1 mid, Lv2 opposite-top, Lv3 IOC, Lv4 market

    @property
    def remaining(self) -> float:
        return self.amount - self.filled_amount


@dataclass(frozen=True)
class FeeContext:
    maker_fee: float  # e.g. 0.0 for futures, 0.0003 for options
    taker_fee: float  # e.g. 0.0005 for futures, 0.0003 for options
    is_post_only: bool = False
    instrument_type: str = "future"  # future, option, weekly_future


@dataclass(frozen=True)
class MicroFeatures:
    orderbook_imbalance: float = 0.0  # -1 to 1
    volatility_estimate: float = 0.0
    trade_flow_imbalance: float = 0.0
    spread_percentile: float = 0.0


@dataclass(frozen=True)
class RecentTrade:
    price: float
    size: float
    direction: str  # "buy" or "sell"
    timestamp: int


# ── MarketSnapshot ──────────────────────────────────────────────────


@dataclass(frozen=True)
class MarketSnapshot:
    """Complete market state visible to a placement algorithm.

    This is the sole input to algorithm.on_update().
    Algorithms must not access any other data source.
    """

    # Market data
    orderbook: OrderBookSnapshot
    ticker: TickerSnapshot
    recent_trades: list[RecentTrade] = field(default_factory=list)

    # My order state
    my_order: MyOrderState = field(default_factory=lambda: MyOrderState(price=0, amount=0))
    direction: str = "buy"
    target_amount: float = 0.0

    # Time and constraints
    elapsed_ms: int = 0
    timeout_ms: int | None = None
    amend_count: int = 0
    price_limit: float | None = None
    tick_size: float = 0.5

    # Fee context
    fee_context: FeeContext = field(default_factory=lambda: FeeContext(maker_fee=0, taker_fee=0.0005))

    # Realized volatility (price units / sqrt(second)); set by SnapshotBuilder via SigmaTracker
    sigma: float = 0.0
    arrival_mid: float = 0.0  # mid_price captured at SmartOrder creation time, for price_limit anchoring
    instrument_class: str = "perp"  # "perp" | "option" | "future"

    # Micro-structure features (for advanced algorithms)
    micro: MicroFeatures = field(default_factory=MicroFeatures)

    @property
    def remaining_time(self) -> float:
        """Normalized remaining time: 1.0 = just started, 0.0 = timed out."""
        if self.timeout_ms is None or self.timeout_ms <= 0:
            return 1.0
        return max(0.0, 1.0 - self.elapsed_ms / self.timeout_ms)

    @property
    def remaining_amount(self) -> float:
        return self.target_amount - self.my_order.filled_amount

    def amend_threshold_ticks(self, k: float | None = None, k_min: int | None = None, dt_seconds: float = 1.0) -> int:
        """Compute σ-based amend threshold in tick units.

        amend_threshold_ticks = max(K_min, ceil(k * σ * sqrt(dt) / tick_size))

        Defaults by class:
          perp:   k=2.0, K_min=1
          option: k=1.0, K_min=1
        """
        import math
        if self.instrument_class == "option":
            k = k if k is not None else 1.0
            k_min = k_min if k_min is not None else 1
        else:
            k = k if k is not None else 2.0
            k_min = k_min if k_min is not None else 1

        if self.sigma <= 0 or self.tick_size <= 0:
            return k_min
        raw = k * self.sigma * math.sqrt(dt_seconds) / self.tick_size
        return max(k_min, int(math.ceil(raw)))


# ── SmartOrderConfig ────────────────────────────────────────────────


Intent = Literal["standard", "urgent"]


@dataclass
class SmartOrderConfig:
    """User-facing configuration for creating a SmartOrder.

    Intent-driven: users pick "standard" (maker-first, escalating) or "urgent"
    (immediate IOC). Algorithm parameters are auto-derived from σ and the
    instrument class. Use the optional override fields only for tuning.
    """

    instrument_name: str
    direction: str  # "buy" or "sell"
    amount: float

    # Intent-driven entry point
    intent: Intent = "standard"

    # Patience budget for escalation (Standard only). Urgent ignores this and
    # starts at Lv3 immediately.
    t_patience_ms: int = 30_000

    # Cap on cross depth for Lv3 IOC (sweep up to N levels of opposite book).
    max_cross_levels: int = 1

    # Class-aware price limits (optional overrides; class-appropriate defaults
    # apply when None).
    price_limit_pct: float | None = None  # perp/future, e.g. 0.003 = ±0.3% of arrival_mid
    price_limit_ticks: int | None = None  # option, e.g. 5 ticks from arrival_mid
    price_limit_iv: float | None = None  # option, e.g. 0.02 = ±2 IV vols (requires BS)

    # Escape hatch: if False, skip post_only=True at Lv0/Lv1 (rare; advanced).
    prefer_maker: bool = True

    def __post_init__(self) -> None:
        if self.price_limit_pct is not None:
            if not (0 < self.price_limit_pct <= 0.05):
                raise ValueError(
                    f"price_limit_pct must be in (0, 0.05], got {self.price_limit_pct}"
                )
        if self.price_limit_ticks is not None:
            if self.price_limit_ticks <= 0:
                raise ValueError(
                    f"price_limit_ticks must be > 0, got {self.price_limit_ticks}"
                )
        if self.price_limit_iv is not None:
            if not (0 < self.price_limit_iv <= 0.2):
                raise ValueError(
                    f"price_limit_iv must be in (0, 0.2], got {self.price_limit_iv}"
                )
        if self.t_patience_ms <= 0:
            raise ValueError(f"t_patience_ms must be > 0, got {self.t_patience_ms}")
        if self.max_cross_levels < 1:
            raise ValueError(
                f"max_cross_levels must be >= 1, got {self.max_cross_levels}"
            )
