"""Account and portfolio models."""

from pydantic import BaseModel

from .position import Position
from .ticker import Greeks


class AccountSummary(BaseModel, extra="ignore"):
    """Account summary from Deribit."""

    currency: str
    equity: float
    balance: float
    margin_balance: float
    available_funds: float
    available_withdrawal_funds: float | None = None

    # Margin usage
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0

    # PnL
    total_pl: float = 0.0
    session_rpl: float = 0.0
    session_upl: float = 0.0
    futures_pl: float | None = None
    options_pl: float | None = None

    # Extended fields (from extended=true)
    delta_total: float | None = None
    options_gamma: float | None = None
    options_vega: float | None = None
    options_theta: float | None = None
    fee_balance: float | None = None


class GreeksSummary(BaseModel):
    """Aggregated Greeks across all positions."""

    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0


class PortfolioSnapshot(BaseModel):
    """Complete portfolio snapshot at a point in time."""

    timestamp: int
    currency: str
    equity: float
    balance: float
    unrealized_pnl: float
    realized_pnl: float
    positions: list[Position]
    greeks_summary: GreeksSummary
