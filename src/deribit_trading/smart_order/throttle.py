"""Global amend throttler for SmartOrders.

Ensures total matching-engine requests stay within rate limits.
Prioritizes orders with larger price deviations.
Merges rapid consecutive amends for the same order.

Recovery path: post_only-reject re-places bypass the normal merge/throttle but
are still subject to a 5 req/s hard cap (per SmartOrder).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

DEFAULT_MAX_AMENDS_PER_SEC = 3  # Conservative, leaves room for other operations
RECOVERY_HARD_CAP_PER_SEC = 5  # post_only re-place hard cap per SmartOrder


@dataclass(order=True)
class AmendRequest:
    """A pending amend request in the priority queue."""

    priority: float  # lower = higher priority (negative deviation)
    order_id: str = field(compare=False)
    new_price: float = field(compare=False)
    post_only: bool = field(compare=False, default=True)
    timestamp: float = field(compare=False, default_factory=time.monotonic)


# Executor signature: async fn(order_id, new_price, post_only)
ExecutorFn = Callable[[str, float, bool], Coroutine[Any, Any, Any]]


class AmendThrottle:
    """Global throttler that rate-limits amend operations across all SmartOrders."""

    def __init__(
        self,
        max_per_second: float = DEFAULT_MAX_AMENDS_PER_SEC,
        executor: ExecutorFn | None = None,
    ) -> None:
        self._max_per_second = max_per_second
        self._min_interval = 1.0 / max_per_second
        self._executor = executor
        self._pending: dict[str, AmendRequest] = {}
        self._last_execute_time = 0.0
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # Recovery hard-cap tracking: per-SmartOrder timestamp deque (last 1s)
        self._recovery_history: dict[str, deque[float]] = defaultdict(deque)

    def set_executor(self, executor: ExecutorFn) -> None:
        self._executor = executor

    def enqueue(
        self,
        order_id: str,
        new_price: float,
        current_price: float,
        post_only: bool = True,
    ) -> None:
        """Enqueue an amend request. Merges with any pending request for the same order."""
        deviation = abs(new_price - current_price) / current_price if current_price > 0 else 0
        priority = -deviation

        self._pending[order_id] = AmendRequest(
            priority=priority,
            order_id=order_id,
            new_price=new_price,
            post_only=post_only,
        )

    def can_enqueue_recovery(self, smart_order_id: str) -> bool:
        """Returns False if this SmartOrder has hit the recovery hard cap."""
        now = time.monotonic()
        hist = self._recovery_history[smart_order_id]
        while hist and hist[0] < now - 1.0:
            hist.popleft()
        return len(hist) < RECOVERY_HARD_CAP_PER_SEC

    def record_recovery(self, smart_order_id: str) -> None:
        """Record a recovery re-place for hard-cap accounting."""
        self._recovery_history[smart_order_id].append(time.monotonic())

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _process_loop(self) -> None:
        try:
            while self._running:
                if not self._pending:
                    await asyncio.sleep(0.05)
                    continue

                now = time.monotonic()
                elapsed = now - self._last_execute_time
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)

                if not self._pending:
                    continue

                best_id = min(self._pending, key=lambda k: self._pending[k].priority)
                request = self._pending.pop(best_id)

                if self._executor:
                    try:
                        await self._executor(request.order_id, request.new_price, request.post_only)
                        self._last_execute_time = time.monotonic()
                    except Exception as e:
                        logger.warning("Amend failed for %s: %s", request.order_id, e)

        except asyncio.CancelledError:
            pass
