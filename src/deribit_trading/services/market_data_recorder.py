"""MarketDataRecorder: persists ticker data and aggregates OHLCV candles."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..client import DeribitClient
from ..persistence import Database
from ..persistence.repositories import MarketCandleRepo, MarketTickerRepo

logger = logging.getLogger(__name__)


@dataclass
class CandleWindow:
    """In-memory OHLCV aggregation window."""

    instrument: str
    resolution_ms: int
    window_start: int = 0
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: float = 0
    count: int = 0

    def update(self, price: float, volume: float, timestamp: int) -> None:
        if self.count == 0:
            self.window_start = (timestamp // self.resolution_ms) * self.resolution_ms
            self.open = price
            self.high = price
            self.low = price
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.count += 1

    def is_window_complete(self, timestamp: int) -> bool:
        if self.count == 0:
            return False
        current_window = (timestamp // self.resolution_ms) * self.resolution_ms
        return current_window > self.window_start

    def flush(self) -> tuple[int, float, float, float, float, float]:
        """Return (window_start, open, high, low, close, volume) and reset."""
        result = (self.window_start, self.open, self.high, self.low, self.close, self.volume)
        self.count = 0
        self.volume = 0
        return result


RESOLUTION_MAP = {
    "1m": 60_000,
    "5m": 300_000,
    "1h": 3_600_000,
}


class MarketDataRecorder:
    """Records ticker data to SQLite and aggregates OHLCV candles in real-time."""

    def __init__(
        self,
        client: DeribitClient,
        db: Database,
        env: str = "testnet",
        resolutions: list[str] | None = None,
    ) -> None:
        self._client = client
        self._ticker_repo = MarketTickerRepo(db)
        self._candle_repo = MarketCandleRepo(db)
        self._env = env
        self._resolutions = resolutions or ["1m", "5m"]
        self._windows: dict[str, list[CandleWindow]] = {}  # instrument → windows
        self._recording = False

    async def start_recording(self, instruments: list[str]) -> None:
        """Subscribe to ticker channels and start recording."""
        if self._recording:
            return

        for inst in instruments:
            self._windows[inst] = [
                CandleWindow(instrument=inst, resolution_ms=RESOLUTION_MAP[r])
                for r in self._resolutions
                if r in RESOLUTION_MAP
            ]

        channels = [f"ticker.{inst}.raw" for inst in instruments]
        await self._client.subscribe(channels, self._on_ticker)
        self._recording = True
        logger.info("MarketDataRecorder started for %s", instruments)

    async def stop_recording(self) -> None:
        """Flush remaining candles and stop."""
        # Flush all open windows
        for inst, windows in self._windows.items():
            for w in windows:
                if w.count > 0:
                    await self._flush_window(w)
        self._recording = False

    async def backfill(
        self,
        instrument: str,
        resolution: str,
        since: int,
        until: int,
    ) -> int:
        """Backfill historical candles from Deribit API.

        Returns the number of candles inserted.
        """
        result = await self._client.call("public/get_tradingview_chart_data", {
            "instrument_name": instrument,
            "start_timestamp": since,
            "end_timestamp": until,
            "resolution": resolution,
        })

        ticks = result.get("ticks", [])
        opens = result.get("open", [])
        highs = result.get("high", [])
        lows = result.get("low", [])
        closes = result.get("close", [])
        volumes = result.get("volume", [])

        candles = []
        for i in range(len(ticks)):
            candles.append((
                ticks[i], self._env, instrument, resolution,
                opens[i], highs[i], lows[i], closes[i],
                volumes[i] if i < len(volumes) else 0,
            ))

        if candles:
            await self._candle_repo.save_candles_batch(candles)

        logger.info("Backfilled %d candles for %s (%s)", len(candles), instrument, resolution)
        return len(candles)

    async def _on_ticker(self, channel: str, data: Any) -> None:
        """Handle ticker update: persist and aggregate candles."""
        if not isinstance(data, dict):
            return

        instrument = data.get("instrument_name", "")
        timestamp = data.get("timestamp", int(time.time() * 1000))

        # Persist raw ticker
        await self._ticker_repo.save_ticker(
            timestamp=timestamp,
            env=self._env,
            instrument_name=instrument,
            mark_price=data.get("mark_price"),
            index_price=data.get("index_price"),
            last_price=data.get("last_price"),
            best_bid=data.get("best_bid_price"),
            best_ask=data.get("best_ask_price"),
            implied_volatility=data.get("iv"),
            funding_rate=data.get("current_funding"),
            volume_24h=data.get("volume_usd"),
        )

        # Update candle windows
        last_price = data.get("last_price") or data.get("mark_price") or 0
        volume = data.get("volume_usd", 0) or 0

        windows = self._windows.get(instrument, [])
        for w in windows:
            if w.is_window_complete(timestamp):
                await self._flush_window(w)
            w.update(last_price, 0, timestamp)  # volume handled per-candle

    async def _flush_window(self, w: CandleWindow) -> None:
        """Write completed candle window to database."""
        ts, o, h, l, c, v = w.flush()
        resolution_str = {v: k for k, v in RESOLUTION_MAP.items()}.get(w.resolution_ms, "1m")
        await self._candle_repo.save_candle(
            timestamp=ts,
            env=self._env,
            instrument_name=w.instrument,
            resolution=resolution_str,
            open=o, high=h, low=l, close=c, volume=v,
        )
