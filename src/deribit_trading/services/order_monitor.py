"""OrderMonitor: real-time order and trade monitoring via WebSocket subscriptions."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from ..client import DeribitClient
from ..config.account_manager import AccountManager
from ..persistence import Database, OrderRepo, TradeRepo

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], None] | Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class OrderMonitor:
    """Subscribes to user.orders and user.trades, persists changes, emits events."""

    def __init__(
        self,
        client: DeribitClient,
        db: Database,
        env: str = "testnet",
        account_manager: AccountManager | None = None,
    ) -> None:
        self._client = client
        self._order_repo = OrderRepo(db)
        self._trade_repo = TradeRepo(db)
        self._env = env
        self._account_manager = account_manager
        self._order_callbacks: list[EventCallback] = []
        self._trade_callbacks: list[EventCallback] = []
        self._subscribed_instruments: set[str] = set()

    def _current_account_id(self) -> str:
        if self._account_manager and self._account_manager.active_id:
            return self._account_manager.active_id
        return self._env

    def on_order_change(self, callback: EventCallback) -> None:
        self._order_callbacks.append(callback)

    def on_trade(self, callback: EventCallback) -> None:
        self._trade_callbacks.append(callback)

    async def subscribe_instrument(self, instrument: str) -> None:
        """Start monitoring orders and trades for an instrument."""
        if instrument in self._subscribed_instruments:
            return

        await self._client.subscribe(
            [f"user.orders.{instrument}.raw"],
            self._on_order_update,
        )
        await self._client.subscribe(
            [f"user.trades.{instrument}.raw"],
            self._on_trade_update,
        )
        self._subscribed_instruments.add(instrument)
        logger.info("OrderMonitor: subscribed to %s", instrument)

    async def subscribe_currency(self, currency: str) -> None:
        """Monitor all orders and trades for a currency."""
        await self._client.subscribe(
            [f"user.orders.any.any.raw"],
            self._on_order_update,
        )
        await self._client.subscribe(
            [f"user.trades.any.any.raw"],
            self._on_trade_update,
        )
        logger.info("OrderMonitor: subscribed to all instruments")

    async def _on_order_update(self, channel: str, data: Any) -> None:
        """Handle order status change from Deribit."""
        orders = data if isinstance(data, list) else [data]
        for order_data in orders:
            await self._persist_order(order_data)
            self._emit_order(order_data)

    async def _on_trade_update(self, channel: str, data: Any) -> None:
        """Handle trade notification from Deribit."""
        trades = data if isinstance(data, list) else [data]
        for trade_data in trades:
            await self._persist_trade(trade_data)
            self._emit_trade(trade_data)

    async def _persist_order(self, data: dict[str, Any]) -> None:
        try:
            await self._order_repo.save(
                order_id=data.get("order_id", ""),
                account_id=self._current_account_id(),
                timestamp=data.get("creation_timestamp", 0),
                instrument_name=data.get("instrument_name", ""),
                direction=data.get("direction", ""),
                order_type=data.get("order_type", ""),
                price=data.get("price"),
                amount=data.get("amount", 0),
                filled_amount=data.get("filled_amount", 0),
                order_state=data.get("order_state", ""),
                label=data.get("label"),
            )
        except Exception as e:
            logger.warning("Failed to persist order: %s", e)

    async def _persist_trade(self, data: dict[str, Any]) -> None:
        try:
            await self._trade_repo.save(
                trade_id=data.get("trade_id", ""),
                account_id=self._current_account_id(),
                timestamp=data.get("timestamp", 0),
                instrument_name=data.get("instrument_name", ""),
                direction=data.get("direction", ""),
                price=data.get("price", 0),
                amount=data.get("amount", 0),
                fee=data.get("fee", 0),
                fee_currency=data.get("fee_currency", ""),
                pnl=data.get("profit_loss"),
                order_id=data.get("order_id", ""),
                label=data.get("label"),
            )
        except Exception as e:
            logger.warning("Failed to persist trade: %s", e)

    def _emit_order(self, data: dict[str, Any]) -> None:
        for cb in self._order_callbacks:
            result = cb("order_change", data)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

    def _emit_trade(self, data: dict[str, Any]) -> None:
        for cb in self._trade_callbacks:
            result = cb("trade", data)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
