"""Ticker and Greeks models for market data snapshots."""

from pydantic import BaseModel


class Greeks(BaseModel, extra="ignore"):
    """Option Greeks values."""

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


class Ticker(BaseModel, extra="ignore"):
    """Real-time market data snapshot for an instrument."""

    instrument_name: str
    timestamp: int

    # Prices
    last_price: float | None = None
    best_bid_price: float | None = None
    best_bid_amount: float | None = None
    best_ask_price: float | None = None
    best_ask_amount: float | None = None
    mark_price: float
    index_price: float | None = None

    # Volume
    volume_24h: float | None = None
    volume_usd_24h: float | None = None
    open_interest: float | None = None

    # Price range
    high_24h: float | None = None
    low_24h: float | None = None
    price_change_24h: float | None = None

    # Option-specific
    implied_volatility: float | None = None
    greeks: Greeks | None = None
    underlying_price: float | None = None

    # Perpetual-specific
    funding_8h: float | None = None
    current_funding: float | None = None

    @property
    def mid_price(self) -> float | None:
        if self.best_bid_price is not None and self.best_ask_price is not None:
            return (self.best_bid_price + self.best_ask_price) / 2
        return self.last_price

    @property
    def spread(self) -> float | None:
        if self.best_bid_price is not None and self.best_ask_price is not None:
            return self.best_ask_price - self.best_bid_price
        return None
