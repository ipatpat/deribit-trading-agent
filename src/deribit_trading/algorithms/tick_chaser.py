"""TickChaser: baseline algorithm that follows the best bid/ask.

Amends the order when the best price moves by more than min_ticks.
Simple, fast, and effective for liquid markets.
"""

from ..smart_order.types import Action, MarketSnapshot
from . import register_algorithm


@register_algorithm
class TickChaser:
    """Follow the best bid/ask with a configurable offset and threshold."""

    name = "tick-chaser"

    def __init__(
        self,
        offset_ticks: int = 0,
        min_ticks: int = 2,
    ) -> None:
        self.offset_ticks = offset_ticks  # ticks above best_bid (buy) or below best_ask (sell)
        self.min_ticks = min_ticks  # minimum price change to trigger amend

    def initial_price(self, snapshot: MarketSnapshot) -> float:
        return self._target_price(snapshot)

    def on_update(self, snapshot: MarketSnapshot) -> Action:
        # Check timeout
        if snapshot.timeout_ms and snapshot.elapsed_ms >= snapshot.timeout_ms:
            return Action.MARKET

        # Check price limit breach
        target = self._target_price(snapshot)
        if not self._within_limit(target, snapshot):
            return Action.CANCEL

        # Check if move is large enough to warrant amend
        diff_ticks = abs(target - snapshot.my_order.price) / snapshot.tick_size
        if diff_ticks >= self.min_ticks:
            return Action.amend(target)

        return Action.HOLD

    def on_fill(self, fill_price: float, fill_amount: float) -> None:
        pass

    def _target_price(self, snapshot: MarketSnapshot) -> float:
        offset = self.offset_ticks * snapshot.tick_size
        if snapshot.direction == "buy":
            return snapshot.orderbook.best_bid + offset
        else:
            return snapshot.orderbook.best_ask - offset

    def _within_limit(self, price: float, snapshot: MarketSnapshot) -> bool:
        if snapshot.price_limit is None:
            return True
        if snapshot.direction == "buy":
            return price <= snapshot.price_limit
        else:
            return price >= snapshot.price_limit
