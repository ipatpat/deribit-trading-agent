"""Builds MarketSnapshot from live market data and order state."""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any

from .types import (
    FeeContext,
    MarketSnapshot,
    MicroFeatures,
    MyOrderState,
    OrderBookLevel,
    OrderBookSnapshot,
    RecentTrade,
    TickerSnapshot,
)


class SnapshotBuilder:
    """Assembles MarketSnapshot from raw Deribit data.

    Maintains a rolling window of prices for volatility estimation.
    """

    def __init__(self, max_price_history: int = 100) -> None:
        self._price_history: deque[float] = deque(maxlen=max_price_history)
        self._trade_history: deque[RecentTrade] = deque(maxlen=50)
        self._last_orderbook: dict[str, Any] = {}
        self._last_ticker: dict[str, Any] = {}

    def update_orderbook(self, data: dict[str, Any]) -> None:
        self._last_orderbook = data

    def update_ticker(self, data: dict[str, Any]) -> None:
        self._last_ticker = data
        mark = data.get("mark_price")
        if mark:
            self._price_history.append(mark)

    def add_public_trade(self, trade: dict[str, Any]) -> None:
        self._trade_history.append(RecentTrade(
            price=trade.get("price", 0),
            size=trade.get("amount", 0),
            direction=trade.get("direction", "buy"),
            timestamp=trade.get("timestamp", 0),
        ))

    def build(
        self,
        my_order: MyOrderState,
        direction: str,
        target_amount: float,
        elapsed_ms: int,
        timeout_ms: int | None,
        amend_count: int,
        price_limit: float | None,
        tick_size: float,
        fee_context: FeeContext,
    ) -> MarketSnapshot:
        orderbook = self._build_orderbook()
        ticker = self._build_ticker()
        micro = self._build_micro_features(orderbook)

        return MarketSnapshot(
            orderbook=orderbook,
            ticker=ticker,
            recent_trades=list(self._trade_history),
            my_order=my_order,
            direction=direction,
            target_amount=target_amount,
            elapsed_ms=elapsed_ms,
            timeout_ms=timeout_ms,
            amend_count=amend_count,
            price_limit=price_limit,
            tick_size=tick_size,
            fee_context=fee_context,
            micro=micro,
        )

    def _build_orderbook(self) -> OrderBookSnapshot:
        raw = self._last_orderbook
        bids = [OrderBookLevel(price=b[0], size=b[1]) for b in raw.get("bids", [])]
        asks = [OrderBookLevel(price=a[0], size=a[1]) for a in raw.get("asks", [])]
        return OrderBookSnapshot(bids=bids, asks=asks)

    def _build_ticker(self) -> TickerSnapshot:
        t = self._last_ticker
        greeks = t.get("greeks", {}) or {}
        return TickerSnapshot(
            mark_price=t.get("mark_price", 0),
            index_price=t.get("index_price"),
            last_price=t.get("last_price"),
            funding_rate=t.get("current_funding"),
            implied_vol=t.get("iv"),
            delta=greeks.get("delta"),
            gamma=greeks.get("gamma"),
            theta=greeks.get("theta"),
            vega=greeks.get("vega"),
        )

    def _build_micro_features(self, ob: OrderBookSnapshot) -> MicroFeatures:
        # Orderbook imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
        bid_vol = sum(l.size for l in ob.bids[:5])
        ask_vol = sum(l.size for l in ob.asks[:5])
        total_vol = bid_vol + ask_vol
        imbalance = (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

        # Volatility estimate from recent price changes
        vol = self._estimate_volatility()

        # Trade flow imbalance from recent trades
        buy_vol = sum(t.size for t in self._trade_history if t.direction == "buy")
        sell_vol = sum(t.size for t in self._trade_history if t.direction == "sell")
        trade_total = buy_vol + sell_vol
        trade_imbalance = (buy_vol - sell_vol) / trade_total if trade_total > 0 else 0.0

        return MicroFeatures(
            orderbook_imbalance=imbalance,
            volatility_estimate=vol,
            trade_flow_imbalance=trade_imbalance,
        )

    def _estimate_volatility(self) -> float:
        """Simple realized volatility from recent price changes."""
        if len(self._price_history) < 3:
            return 0.0

        prices = list(self._price_history)
        returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        if not returns:
            return 0.0

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)
