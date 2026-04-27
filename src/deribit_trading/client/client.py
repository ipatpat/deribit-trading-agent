"""DeribitClient — main API client integrating all components."""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from ..models import (
    AccountSummary,
    Direction,
    Instrument,
    InstrumentKind,
    Order,
    OrderType,
    Position,
    Ticker,
    TimeInForce,
    Trade,
    TriggerType,
)
from .auth import AuthManager
from .connection import WebSocketConnection
from .errors import DeribitConnectionError
from .rate_limiter import RateLimiter
from .rpc import JsonRpcManager

logger = logging.getLogger(__name__)

SubscriptionCallback = Callable[[str, Any], None] | Callable[[str, Any], Coroutine[Any, Any, None]]


class DeribitClient:
    """Type-safe client for the Deribit API.

    Provides both a generic call() method and typed high-level methods.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._connection = WebSocketConnection(url)
        self._rpc = JsonRpcManager(self._connection)
        self._auth = AuthManager(self._rpc)
        self._rate_limiter = RateLimiter()

        # Subscription management
        self._subscriptions: dict[str, list[SubscriptionCallback]] = {}
        self._rpc.set_subscription_handler(self._on_subscription)
        self._connection.set_on_reconnect(self._on_reconnect)

    @property
    def is_connected(self) -> bool:
        return self._connection.is_connected

    @property
    def is_authenticated(self) -> bool:
        return self._auth.is_authenticated

    @property
    def url(self) -> str:
        return self._url

    # ── Connection lifecycle ────────────────────────────────────────

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        await self._connection.connect()

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        await self._auth.logout()
        await self._connection.disconnect()
        self._subscriptions.clear()

    async def authenticate(self, client_id: str, client_secret: str) -> None:
        """Authenticate with client credentials."""
        await self._auth.authenticate(client_id, client_secret)

    # ── Generic JSON-RPC ────────────────────────────────────────────

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> Any:
        """Send a JSON-RPC request with rate limiting."""
        await self._rate_limiter.acquire(method)
        return await self._rpc.call(method, params, timeout)

    # ── Subscription management ─────────────────────────────────────

    async def subscribe(
        self, channels: list[str], callback: SubscriptionCallback
    ) -> None:
        """Subscribe to channels with a callback."""
        for channel in channels:
            if channel not in self._subscriptions:
                self._subscriptions[channel] = []
            self._subscriptions[channel].append(callback)

        # Determine if public or private subscription
        has_private = any(c.startswith("user.") for c in channels)
        method = "private/subscribe" if has_private else "public/subscribe"
        await self.call(method, {"channels": channels})

    async def unsubscribe(self, channels: list[str]) -> None:
        """Unsubscribe from channels."""
        for channel in channels:
            self._subscriptions.pop(channel, None)

        has_private = any(c.startswith("user.") for c in channels)
        method = "private/unsubscribe" if has_private else "public/unsubscribe"
        await self.call(method, {"channels": channels})

    def _on_subscription(self, channel: str, data: Any) -> None:
        """Dispatch subscription data to registered callbacks."""
        callbacks = self._subscriptions.get(channel, [])
        for cb in callbacks:
            result = cb(channel, data)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)

    async def _on_reconnect(self) -> None:
        """Re-authenticate and restore subscriptions after reconnection."""
        # Re-authenticate
        await self._auth.reauthenticate()

        # Re-subscribe to all channels
        if self._subscriptions:
            public_channels = [
                c for c in self._subscriptions if not c.startswith("user.")
            ]
            private_channels = [
                c for c in self._subscriptions if c.startswith("user.")
            ]

            if public_channels:
                await self.call("public/subscribe", {"channels": public_channels})
            if private_channels:
                await self.call("private/subscribe", {"channels": private_channels})

            logger.info(
                "Restored %d subscriptions after reconnect",
                len(self._subscriptions),
            )

    # ── Typed market data methods ───────────────────────────────────

    async def get_ticker(self, instrument_name: str) -> Ticker:
        """Get current ticker for an instrument."""
        result = await self.call("public/ticker", {"instrument_name": instrument_name})
        return Ticker.model_validate(result)

    async def get_instruments(
        self, currency: str, kind: InstrumentKind | None = None, expired: bool = False
    ) -> list[Instrument]:
        """Get available instruments."""
        params: dict[str, Any] = {"currency": currency, "expired": expired}
        if kind:
            params["kind"] = kind
        result = await self.call("public/get_instruments", params)
        return [Instrument.model_validate(i) for i in result]

    async def get_order_book(
        self, instrument_name: str, depth: int = 10
    ) -> dict[str, Any]:
        """Get order book for an instrument."""
        return await self.call(
            "public/get_order_book",
            {"instrument_name": instrument_name, "depth": depth},
        )

    # ── Typed trading methods ───────────────────────────────────────

    async def buy(
        self,
        instrument_name: str,
        amount: float,
        order_type: OrderType = OrderType.LIMIT,
        price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GOOD_TIL_CANCELLED,
        label: str | None = None,
        post_only: bool = False,
        reduce_only: bool = False,
        trigger: TriggerType | None = None,
        trigger_price: float | None = None,
    ) -> Order:
        """Place a buy order."""
        return await self._place_order(
            "private/buy",
            instrument_name=instrument_name,
            amount=amount,
            order_type=order_type,
            price=price,
            time_in_force=time_in_force,
            label=label,
            post_only=post_only,
            reduce_only=reduce_only,
            trigger=trigger,
            trigger_price=trigger_price,
        )

    async def sell(
        self,
        instrument_name: str,
        amount: float,
        order_type: OrderType = OrderType.LIMIT,
        price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.GOOD_TIL_CANCELLED,
        label: str | None = None,
        post_only: bool = False,
        reduce_only: bool = False,
        trigger: TriggerType | None = None,
        trigger_price: float | None = None,
    ) -> Order:
        """Place a sell order."""
        return await self._place_order(
            "private/sell",
            instrument_name=instrument_name,
            amount=amount,
            order_type=order_type,
            price=price,
            time_in_force=time_in_force,
            label=label,
            post_only=post_only,
            reduce_only=reduce_only,
            trigger=trigger,
            trigger_price=trigger_price,
        )

    async def _place_order(self, method: str, **kwargs: Any) -> Order:
        params: dict[str, Any] = {
            "instrument_name": kwargs["instrument_name"],
            "amount": kwargs["amount"],
            "type": kwargs["order_type"],
        }
        if kwargs.get("price") is not None:
            params["price"] = kwargs["price"]
        if kwargs.get("time_in_force"):
            params["time_in_force"] = kwargs["time_in_force"]
        if kwargs.get("label"):
            params["label"] = kwargs["label"]
        if kwargs.get("post_only"):
            params["post_only"] = True
        if kwargs.get("reduce_only"):
            params["reduce_only"] = True
        if kwargs.get("trigger"):
            params["trigger"] = kwargs["trigger"]
        if kwargs.get("trigger_price") is not None:
            params["trigger_price"] = kwargs["trigger_price"]

        result = await self.call(method, params)
        return Order.model_validate(result["order"])

    async def edit(
        self, order_id: str, amount: float, price: float
    ) -> Order:
        """Modify an existing order."""
        result = await self.call("private/edit", {
            "order_id": order_id,
            "amount": amount,
            "price": price,
        })
        return Order.model_validate(result["order"])

    async def cancel(self, order_id: str) -> Order:
        """Cancel an order."""
        result = await self.call("private/cancel", {"order_id": order_id})
        return Order.model_validate(result)

    async def cancel_all(
        self,
        currency: str | None = None,
        instrument_name: str | None = None,
    ) -> int:
        """Cancel all orders, optionally filtered by currency or instrument."""
        if instrument_name:
            result = await self.call(
                "private/cancel_all_by_instrument",
                {"instrument_name": instrument_name},
            )
        elif currency:
            result = await self.call(
                "private/cancel_all_by_currency", {"currency": currency}
            )
        else:
            result = await self.call("private/cancel_all", {})
        return result

    async def close_position(
        self, instrument_name: str, order_type: OrderType = OrderType.MARKET
    ) -> Order:
        """Close a position."""
        result = await self.call("private/close_position", {
            "instrument_name": instrument_name,
            "type": order_type,
        })
        return Order.model_validate(result["order"])

    # ── Typed query methods ─────────────────────────────────────────

    async def get_positions(self, currency: str) -> list[Position]:
        """Get all positions for a currency."""
        result = await self.call(
            "private/get_positions", {"currency": currency}
        )
        return [Position.model_validate(p) for p in result]

    async def get_position(self, instrument_name: str) -> Position:
        """Get a single position."""
        result = await self.call(
            "private/get_position", {"instrument_name": instrument_name}
        )
        return Position.model_validate(result)

    async def get_open_orders(
        self, currency: str | None = None, instrument_name: str | None = None
    ) -> list[Order]:
        """Get open orders."""
        if instrument_name:
            result = await self.call(
                "private/get_open_orders_by_instrument",
                {"instrument_name": instrument_name},
            )
        elif currency:
            result = await self.call(
                "private/get_open_orders_by_currency", {"currency": currency}
            )
        else:
            result = await self.call(
                "private/get_open_orders_by_currency", {"currency": "BTC"}
            )
        return [Order.model_validate(o) for o in result]

    async def get_order_state(self, order_id: str) -> Order:
        """Get current state of an order."""
        result = await self.call("private/get_order_state", {"order_id": order_id})
        return Order.model_validate(result)

    async def get_account_summary(self, currency: str, extended: bool = True) -> AccountSummary:
        """Get account summary. extended=True includes delta_total, options greeks."""
        result = await self.call(
            "private/get_account_summary", {"currency": currency, "extended": extended}
        )
        return AccountSummary.model_validate(result)

    async def get_user_trades(
        self, currency: str, count: int = 100
    ) -> list[Trade]:
        """Get recent user trades."""
        result = await self.call("private/get_user_trades_by_currency", {
            "currency": currency,
            "count": count,
        })
        return [Trade.model_validate(t) for t in result.get("trades", [])]

    # ── Utility ─────────────────────────────────────────────────────

    async def enable_cancel_on_disconnect(self) -> None:
        """Enable cancel-on-disconnect safety feature."""
        await self.call("private/enable_cancel_on_disconnect", {})
        logger.info("Cancel on disconnect enabled")
