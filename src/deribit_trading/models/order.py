"""Order model for Deribit orders."""

from pydantic import BaseModel

from .enums import Direction, OrderState, OrderType, TimeInForce, TriggerType


class Order(BaseModel, extra="ignore"):
    """An order on Deribit."""

    order_id: str
    instrument_name: str
    direction: Direction
    order_type: OrderType
    order_state: OrderState
    price: float | None = None
    amount: float
    filled_amount: float = 0.0
    average_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.GOOD_TIL_CANCELLED
    label: str | None = None
    creation_timestamp: int
    last_update_timestamp: int

    # Stop/take order fields
    trigger: TriggerType | None = None
    trigger_price: float | None = None

    # Execution info
    commission: float | None = None
    profit_loss: float | None = None

    # Advanced
    post_only: bool = False
    reduce_only: bool = False

    @property
    def is_open(self) -> bool:
        return self.order_state == OrderState.OPEN

    @property
    def remaining_amount(self) -> float:
        return self.amount - self.filled_amount
