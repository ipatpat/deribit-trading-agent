"""Client-side rate limiter using a token bucket algorithm."""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# Deribit non-matching engine defaults
DEFAULT_MAX_CREDITS = 50_000
DEFAULT_REFILL_RATE = 10_000  # credits per second
DEFAULT_REQUEST_COST = 500

# Known per-method costs
METHOD_COSTS: dict[str, int] = {
    "public/get_instruments": 10_000,
    "public/subscribe": 3_000,
    "public/unsubscribe": 3_000,
    "private/get_transaction_log": 10_000,
    "private/move_positions": 100_000,
}

# Matching engine methods (separate limit pool)
MATCHING_ENGINE_METHODS = frozenset({
    "private/buy",
    "private/sell",
    "private/edit",
    "private/cancel",
    "private/cancel_all",
    "private/cancel_all_by_currency",
    "private/cancel_all_by_instrument",
    "private/close_position",
    "private/mass_quote",
    "private/cancel_quotes",
})


class TokenBucket:
    """A token bucket rate limiter."""

    def __init__(self, max_tokens: int, refill_rate: float) -> None:
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: int) -> None:
        """Wait until enough tokens are available, then consume them."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= cost:
                    self._tokens -= cost
                    return

                # Calculate wait time
                deficit = cost - self._tokens
                wait = deficit / self.refill_rate
                await asyncio.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now


class RateLimiter:
    """Manages rate limiting for Deribit API with separate pools."""

    def __init__(self) -> None:
        # Non-matching engine pool
        self._general = TokenBucket(DEFAULT_MAX_CREDITS, DEFAULT_REFILL_RATE)
        # Matching engine pool (Tier 4 defaults: 5 req/sec sustained, 20 burst)
        self._matching = TokenBucket(max_tokens=20, refill_rate=5)

    async def acquire(self, method: str) -> None:
        """Acquire rate limit tokens for a method call."""
        if method in MATCHING_ENGINE_METHODS:
            await self._matching.acquire(1)
        else:
            cost = METHOD_COSTS.get(method, DEFAULT_REQUEST_COST)
            await self._general.acquire(cost)
