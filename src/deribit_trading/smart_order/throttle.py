"""Global amend throttler for SmartOrders.

Ensures total matching-engine requests stay within rate limits.
Prioritizes orders with larger price deviations.
Merges rapid consecutive amends for the same order.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

DEFAULT_MAX_AMENDS_PER_SEC = 3  # Conservative, leaves room for other operations


@dataclass(order=True)
class AmendRequest:
    """A pending amend request in the priority queue."""

    priority: float  # lower = higher priority (negative deviation)
    order_id: str = field(compare=False)
    new_price: float = field(compare=False)
    timestamp: float = field(compare=False, default_factory=time.monotonic)


class AmendThrottle:
    """Global throttler that rate-limits amend operations across all SmartOrders."""

    def __init__(
        self,
        max_per_second: float = DEFAULT_MAX_AMENDS_PER_SEC,
        executor: Callable[[str, float], Coroutine[Any, Any, Any]] | None = None,
    ) -> None:
        self._max_per_second = max_per_second
        self._min_interval = 1.0 / max_per_second
        self._executor = executor  # async fn(order_id, new_price)
        self._pending: dict[str, AmendRequest] = {}  # latest per order_id
        self._last_execute_time = 0.0
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def set_executor(
        self, executor: Callable[[str, float], Coroutine[Any, Any, Any]]
    ) -> None:
        self._executor = executor

    def enqueue(
        self,
        order_id: str,
        new_price: float,
        current_price: float,
    ) -> None:
        """Enqueue an amend request. Merges with any pending request for the same order."""
        deviation = abs(new_price - current_price) / current_price if current_price > 0 else 0
        priority = -deviation  # Higher deviation = lower priority number = higher priority

        self._pending[order_id] = AmendRequest(
            priority=priority,
            order_id=order_id,
            new_price=new_price,
        )

    async def start(self) -> None:
        """Start the throttle processing loop."""
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Stop the throttle processing loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _process_loop(self) -> None:
        """Process pending amends respecting rate limits."""
        try:
            while self._running:
                if not self._pending:
                    await asyncio.sleep(0.05)
                    continue

                # Wait for rate limit window
                now = time.monotonic()
                elapsed = now - self._last_execute_time
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)

                # Pick highest priority request
                if not self._pending:
                    continue

                # Sort by priority and pick the most urgent
                best_id = min(self._pending, key=lambda k: self._pending[k].priority)
                request = self._pending.pop(best_id)

                # Execute
                if self._executor:
                    try:
                        await self._executor(request.order_id, request.new_price)
                        self._last_execute_time = time.monotonic()
                    except Exception as e:
                        logger.warning("Amend failed for %s: %s", request.order_id, e)

        except asyncio.CancelledError:
            pass
