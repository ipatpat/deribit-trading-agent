"""Trade model for execution records."""

from pydantic import BaseModel

from .enums import Direction


class Trade(BaseModel, extra="ignore"):
    """A trade execution record."""

    trade_id: str
    instrument_name: str
    direction: Direction
    price: float
    amount: float
    fee: float
    fee_currency: str
    order_id: str
    timestamp: int

    # PnL (available for closing trades)
    profit_loss: float | None = None

    # Context
    label: str | None = None
    index_price: float | None = None
    mark_price: float | None = None
