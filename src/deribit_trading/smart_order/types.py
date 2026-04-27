"""Core types for the smart order engine.

MarketSnapshot is the sole input to placement algorithms.
Action is the sole output. This boundary keeps algorithms pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


# ── Action ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Action:
    """Decision output from a placement algorithm."""

    kind: str  # "hold", "amend", "cancel", "market"
    price: float | None = None

    HOLD: Action = None  # type: ignore[assignment]  # set below
    CANCEL: Action = None  # type: ignore[assignment]
    MARKET: Action = None  # type: ignore[assignment]

    @classmethod
    def amend(cls, new_price: float) -> Action:
        return cls(kind="amend", price=new_price)


# Singleton instances
Action.HOLD = Action(kind="hold")
Action.CANCEL = Action(kind="cancel")
Action.MARKET = Action(kind="market")


# ── SmartOrder state ────────────────────────────────────────────────


class SmartOrderState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
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


# ── SmartOrderConfig ────────────────────────────────────────────────


@dataclass
class SmartOrderConfig:
    """User-facing configuration for creating a SmartOrder."""

    instrument_name: str
    direction: str  # "buy" or "sell"
    amount: float
    algorithm: str = "tick-chaser"
    algo_params: dict = field(default_factory=dict)
    price_limit: float | None = None
    timeout_ms: int | None = 120_000  # default 2 minutes
    prefer_maker: bool = True
    patience: float = 0.5  # 0.0 (aggressive) to 1.0 (patient)
