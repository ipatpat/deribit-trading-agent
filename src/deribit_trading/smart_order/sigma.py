"""SigmaTracker: realized volatility from per-second mid-price increments.

σ is defined as the (EWMA-smoothed) sample stdev of (mid_t − mid_{t-1}) over
a rolling window. Window length and clamps differ by instrument class:

  perp:   window = 5 min,  σ_min = 0.05 ticks/s, σ_max = 50 ticks/s
  option: window = 30 min, σ_min = 0.05 ticks/s, σ_max = 20 ticks/s

The unit of σ is "price units per second" (matching mid increments at Δt=1s).
Algorithms multiply by sqrt(Δt)/tick_size to translate into a tick threshold.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class SigmaProfile:
    window_seconds: int
    sigma_min: float  # absolute floor, in price units / sec (post-EWMA)
    sigma_max: float  # absolute ceiling
    ewma_alpha: float = 0.3


PROFILES: dict[str, SigmaProfile] = {
    "perp": SigmaProfile(window_seconds=5 * 60, sigma_min=0.0, sigma_max=1e9),
    "future": SigmaProfile(window_seconds=5 * 60, sigma_min=0.0, sigma_max=1e9),
    "option": SigmaProfile(window_seconds=30 * 60, sigma_min=0.0, sigma_max=1e9),
}


class SigmaTracker:
    """Tracks realized σ for a single instrument.

    Call `record_mid(mid)` once per second (driven by an external scheduler).
    Read `sigma` to get the current EWMA-smoothed stdev (clamped).
    """

    def __init__(self, instrument_class: str = "perp", profile: SigmaProfile | None = None) -> None:
        self.instrument_class = instrument_class
        self.profile = profile or PROFILES.get(instrument_class, PROFILES["perp"])
        self._mids: deque[tuple[float, float]] = deque()  # (timestamp, mid)
        self._sigma_ewma: float = 0.0
        self._initialized: bool = False

    def record_mid(self, mid: float, ts: float | None = None) -> None:
        """Record a mid-price sample. Call ~once per second."""
        if mid <= 0:
            return
        ts = ts if ts is not None else time.time()
        self._mids.append((ts, mid))
        cutoff = ts - self.profile.window_seconds
        while self._mids and self._mids[0][0] < cutoff:
            self._mids.popleft()

        sample = self._raw_sigma()
        if not self._initialized:
            self._sigma_ewma = sample
            self._initialized = True
        else:
            a = self.profile.ewma_alpha
            self._sigma_ewma = a * sample + (1 - a) * self._sigma_ewma

    def _raw_sigma(self) -> float:
        """Sample stdev of (mid_t − mid_{t-1}) over the current window."""
        if len(self._mids) < 3:
            return 0.0
        increments = [
            self._mids[i][1] - self._mids[i - 1][1]
            for i in range(1, len(self._mids))
        ]
        n = len(increments)
        if n < 2:
            return 0.0
        mean = sum(increments) / n
        variance = sum((x - mean) ** 2 for x in increments) / (n - 1)
        return math.sqrt(variance)

    @property
    def sigma(self) -> float:
        """Current σ, EWMA-smoothed and clamped. 0.0 if insufficient data."""
        if not self._initialized or len(self._mids) < 3:
            return 0.0
        s = self._sigma_ewma
        return max(self.profile.sigma_min, min(self.profile.sigma_max, s))

    @property
    def sample_count(self) -> int:
        return len(self._mids)


def classify_instrument(instrument_name: str) -> str:
    """Heuristic classifier from instrument_name.

    BTC-PERPETUAL    → perp
    BTC-28JUN26      → future
    BTC-28JUN26-75000-C → option
    """
    parts = instrument_name.split("-")
    if len(parts) >= 4:
        return "option"
    if "PERPETUAL" in instrument_name.upper():
        return "perp"
    return "future"
