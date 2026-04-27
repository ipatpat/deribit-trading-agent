"""TimedEscalation: time-based price escalation toward market price.

Phase 1 (patience): behave like TickChaser, follow best bid/ask.
Phase 2 (escalation): progressively move toward market price.
Phase 3 (timeout): convert to market or cancel.
"""

from ..smart_order.types import Action, MarketSnapshot
from . import register_algorithm


@register_algorithm
class TimedEscalation:
    """Escalate price toward market over time."""

    name = "timed-escalation"

    def __init__(
        self,
        offset_ticks: int = 0,
        min_ticks: int = 2,
        patience_ms: int = 30_000,
        step_interval_ms: int = 10_000,
        step_ticks: int = 1,
        timeout_action: str = "market",  # "market" or "cancel"
    ) -> None:
        self.offset_ticks = offset_ticks
        self.min_ticks = min_ticks
        self.patience_ms = patience_ms
        self.step_interval_ms = step_interval_ms
        self.step_ticks = step_ticks
        self.timeout_action = timeout_action
        self._escalation_steps = 0

    def initial_price(self, snapshot: MarketSnapshot) -> float:
        return self._best_price(snapshot)

    def on_update(self, snapshot: MarketSnapshot) -> Action:
        # Timeout → exit
        if snapshot.timeout_ms and snapshot.elapsed_ms >= snapshot.timeout_ms:
            return Action.MARKET if self.timeout_action == "market" else Action.CANCEL

        # Phase 1: patience — follow best like TickChaser
        if snapshot.elapsed_ms < self.patience_ms:
            return self._follow_best(snapshot)

        # Phase 2: escalation — step toward market price
        escalation_elapsed = snapshot.elapsed_ms - self.patience_ms
        expected_steps = escalation_elapsed // self.step_interval_ms

        if expected_steps > self._escalation_steps:
            self._escalation_steps = expected_steps
            return self._escalate(snapshot)

        # Between steps: still follow best if it moved significantly
        return self._follow_best(snapshot)

    def on_fill(self, fill_price: float, fill_amount: float) -> None:
        pass

    def _best_price(self, snapshot: MarketSnapshot) -> float:
        offset = self.offset_ticks * snapshot.tick_size
        if snapshot.direction == "buy":
            return snapshot.orderbook.best_bid + offset
        else:
            return snapshot.orderbook.best_ask - offset

    def _follow_best(self, snapshot: MarketSnapshot) -> Action:
        target = self._best_price(snapshot)
        if not self._within_limit(target, snapshot):
            return Action.CANCEL

        diff_ticks = abs(target - snapshot.my_order.price) / snapshot.tick_size
        if diff_ticks >= self.min_ticks:
            return Action.amend(target)
        return Action.HOLD

    def _escalate(self, snapshot: MarketSnapshot) -> Action:
        step = self.step_ticks * snapshot.tick_size
        if snapshot.direction == "buy":
            new_price = snapshot.my_order.price + step
        else:
            new_price = snapshot.my_order.price - step

        if not self._within_limit(new_price, snapshot):
            return Action.CANCEL

        return Action.amend(new_price)

    def _within_limit(self, price: float, snapshot: MarketSnapshot) -> bool:
        if snapshot.price_limit is None:
            return True
        if snapshot.direction == "buy":
            return price <= snapshot.price_limit
        else:
            return price >= snapshot.price_limit
