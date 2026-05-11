"""Market data service for quotes, order books, and option analytics."""

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

from ..client import DeribitClient
from ..models import Instrument, InstrumentKind, Ticker

TickerCallback = Callable[[Ticker], None] | Callable[[Ticker], Coroutine[Any, Any, None]]

# Cap concurrent ticker fetches to avoid Deribit's public-channel rate limits
# (~50 req/s). 20 in-flight is comfortable: ~16x speedup over serial without
# hitting limits.
_TICKER_FETCH_CONCURRENCY = 20


async def _fetch_tickers_bounded(
    client: DeribitClient, instruments: list[Instrument]
) -> list[Ticker]:
    """Fetch tickers for many instruments with bounded concurrency."""
    sem = asyncio.Semaphore(_TICKER_FETCH_CONCURRENCY)

    async def _one(inst: Instrument) -> Ticker:
        async with sem:
            return await client.get_ticker(inst.instrument_name)

    return await asyncio.gather(*(_one(i) for i in instruments))


class MarketDataService:
    """Provides market data queries and real-time subscriptions."""

    def __init__(self, client: DeribitClient) -> None:
        self._client = client

    async def get_ticker(self, instrument_name: str) -> Ticker:
        return await self._client.get_ticker(instrument_name)

    async def subscribe_tickers(
        self, instruments: list[str], callback: TickerCallback
    ) -> None:
        """Subscribe to ticker updates for multiple instruments."""
        channels = [f"ticker.{name}.raw" for name in instruments]

        def _on_data(channel: str, data: Any) -> None:
            ticker = Ticker.model_validate(data)
            result = callback(ticker)
            import asyncio
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

        await self._client.subscribe(channels, _on_data)

    async def get_orderbook(
        self, instrument_name: str, depth: int = 10
    ) -> dict[str, Any]:
        return await self._client.get_order_book(instrument_name, depth)

    async def get_instruments(
        self,
        currency: str,
        kind: InstrumentKind | None = None,
    ) -> list[Instrument]:
        return await self._client.get_instruments(currency, kind)

    async def get_option_chain(
        self, currency: str, expiry_timestamp: int | None = None
    ) -> dict[str, list[Ticker]]:
        """Get option chain grouped by expiry.

        Returns dict mapping expiry string to list of option tickers.
        Tickers within an expiry are fetched concurrently to avoid the N+1
        serial-await trap (ETH chain has 800+ options).
        """
        options = await self._client.get_instruments(currency, InstrumentKind.OPTION)

        if expiry_timestamp:
            options = [o for o in options if o.expiration_timestamp == expiry_timestamp]

        # Group by expiry
        by_expiry: dict[int, list[Instrument]] = defaultdict(list)
        for opt in options:
            if opt.expiration_timestamp:
                by_expiry[opt.expiration_timestamp].append(opt)

        result: dict[str, list[Ticker]] = {}
        for exp_ts, instruments in sorted(by_expiry.items()):
            # Bounded concurrent fetch to avoid hitting Deribit rate limits.
            tickers = await _fetch_tickers_bounded(self._client, instruments)
            result[str(exp_ts)] = list(tickers)

        return result

    async def get_vol_surface(self, currency: str) -> dict[str, dict[float, float]]:
        """Build volatility surface: {expiry: {strike: implied_vol}}.

        Returns a nested dict mapping expiry timestamps to strike→IV mappings.
        Tickers fetched concurrently per expiry.
        """
        options = await self._client.get_instruments(currency, InstrumentKind.OPTION)

        by_expiry: dict[int, list[Instrument]] = defaultdict(list)
        for opt in options:
            if opt.expiration_timestamp:
                by_expiry[opt.expiration_timestamp].append(opt)

        surface: dict[str, dict[float, float]] = {}
        for exp_ts, instruments in sorted(by_expiry.items()):
            strike_instruments = [i for i in instruments if i.strike is not None]
            tickers = await _fetch_tickers_bounded(self._client, strike_instruments)
            strike_iv: dict[float, float] = {}
            for inst, ticker in zip(strike_instruments, tickers):
                if inst.strike is not None and ticker.implied_volatility is not None:
                    strike_iv[inst.strike] = ticker.implied_volatility
            if strike_iv:
                surface[str(exp_ts)] = strike_iv

        return surface
