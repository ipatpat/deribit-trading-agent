"""Position model for holdings on Deribit."""

from pydantic import BaseModel

from .enums import Direction, InstrumentKind


class Position(BaseModel, extra="ignore"):
    """A position held on Deribit."""

    instrument_name: str
    kind: InstrumentKind
    direction: Direction
    size: float
    average_price: float
    mark_price: float
    index_price: float | None = None

    # PnL
    realized_profit_loss: float = 0.0
    floating_profit_loss: float = 0.0
    total_profit_loss: float = 0.0

    # Margin
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0

    # Leverage
    leverage: int | None = None

    # Option Greeks (populated for option positions)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
