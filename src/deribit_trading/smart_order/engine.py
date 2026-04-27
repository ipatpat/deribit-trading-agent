"""SmartOrderEngine: manages multiple SmartOrders with event-driven updates."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from ..algorithms import PlacementAlgorithm, get_algorithm
from ..client import DeribitClient
from ..client.errors import DeribitAPIError
from .fee_logic import build_fee_context, should_use_post_only
from .snapshot_builder import SnapshotBuilder
from .throttle import AmendThrottle
from .types import (
    Action,
    FeeContext,
    MyOrderState,
    SmartOrderConfig,
    SmartOrderState,
)

logger = logging.getLogger(__name__)

SmartOrderCallback = Callable[[str, dict[str, Any]], None] | Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class SmartOrder:
    """A single managed smart order."""

    id: str
    config: SmartOrderConfig
    algorithm: PlacementAlgorithm
    fee_context: FeeContext
    state: SmartOrderState = SmartOrderState.PENDING
    deribit_order_id: str | None = None
    current_price: float = 0.0
    filled_amount: float = 0.0
    amend_count: int = 0
    created_at: float = field(default_factory=time.time)
    tick_size: float = 0.5

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.created_at) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instrument": self.config.instrument_name,
            "direction": self.config.direction,
            "amount": self.config.amount,
            "algorithm": self.config.algorithm,
            "state": self.state,
            "deribit_order_id": self.deribit_order_id,
            "current_price": self.current_price,
            "filled_amount": self.filled_amount,
            "amend_count": self.amend_count,
            "elapsed_ms": self.elapsed_ms,
            "fee_mode": "maker" if self.fee_context.is_post_only else "any",
        }


class SmartOrderEngine:
    """Manages multiple SmartOrders with event-driven market data updates."""

    def __init__(self, client: DeribitClient) -> None:
        self._client = client
        self._orders: dict[str, SmartOrder] = {}
        self._builders: dict[str, SnapshotBuilder] = {}  # per instrument
        self._subscribed_instruments: set[str] = set()
        self._throttle = AmendThrottle()
        self._throttle.set_executor(self._execute_amend)
        self._event_callbacks: list[SmartOrderCallback] = []
        self._risk_manager: Any = None  # Optional RiskManager

    def set_risk_manager(self, rm: Any) -> None:
        self._risk_manager = rm

    async def start(self) -> None:
        """Start the engine's throttle loop."""
        await self._throttle.start()

    async def stop(self) -> None:
        """Stop the engine and cancel all active orders."""
        await self._throttle.stop()
        for so in list(self._orders.values()):
            if so.state == SmartOrderState.ACTIVE:
                await self.cancel_smart_order(so.id)

    def on_event(self, callback: SmartOrderCallback) -> None:
        """Register a callback for SmartOrder events."""
        self._event_callbacks.append(callback)

    # ── Create SmartOrder ───────────────────────────────────────────

    async def create_smart_order(self, config: SmartOrderConfig) -> SmartOrder:
        """Create and start a new SmartOrder."""
        if self._risk_manager:
            self._risk_manager.check(
                config.instrument_name, config.direction,
                config.amount, config.price_limit,
            )
        so_id = f"so-{uuid.uuid4().hex[:8]}"
        fee_ctx = build_fee_context(config.instrument_name)

        # Override post_only preference
        if not config.prefer_maker:
            fee_ctx = FeeContext(
                maker_fee=fee_ctx.maker_fee,
                taker_fee=fee_ctx.taker_fee,
                is_post_only=False,
                instrument_type=fee_ctx.instrument_type,
            )

        algo = get_algorithm(config.algorithm, config.algo_params)

        # Get instrument tick size
        tick_size = 0.5  # default for BTC-PERPETUAL
        try:
            instruments = await self._client.get_instruments(
                config.instrument_name.split("-")[0]
            )
            for inst in instruments:
                if inst.instrument_name == config.instrument_name:
                    tick_size = inst.tick_size
                    break
        except Exception:
            pass

        so = SmartOrder(
            id=so_id,
            config=config,
            algorithm=algo,
            fee_context=fee_ctx,
            tick_size=tick_size,
        )
        self._orders[so_id] = so

        # Ensure subscriptions
        await self._ensure_subscribed(config.instrument_name)

        # Fetch initial market data so the snapshot is not empty
        builder = self._get_builder(config.instrument_name)
        try:
            ob = await self._client.get_order_book(config.instrument_name, depth=10)
            builder.update_orderbook(ob)
            ticker_data = await self._client.call("public/ticker", {"instrument_name": config.instrument_name})
            builder.update_ticker(ticker_data)
        except Exception as e:
            logger.warning("SmartOrder %s: failed to fetch initial data: %s", so_id, e)

        # Build initial snapshot and get price
        initial_snapshot = builder.build(
            my_order=MyOrderState(price=0, amount=config.amount),
            direction=config.direction,
            target_amount=config.amount,
            elapsed_ms=0,
            timeout_ms=config.timeout_ms,
            amend_count=0,
            price_limit=config.price_limit,
            tick_size=tick_size,
            fee_context=fee_ctx,
        )
        initial_price = algo.initial_price(initial_snapshot)

        # Snap to tick
        initial_price = self._snap_to_tick(initial_price, tick_size)

        # Place initial order
        try:
            post_only = should_use_post_only(fee_ctx)
            if config.direction == "buy":
                order = await self._client.buy(
                    instrument_name=config.instrument_name,
                    amount=config.amount,
                    order_type="limit",
                    price=initial_price,
                    post_only=post_only,
                )
            else:
                order = await self._client.sell(
                    instrument_name=config.instrument_name,
                    amount=config.amount,
                    order_type="limit",
                    price=initial_price,
                    post_only=post_only,
                )

            so.deribit_order_id = order.order_id
            so.current_price = initial_price
            so.state = SmartOrderState.ACTIVE
            logger.info(
                "SmartOrder %s created: %s %s %s @ %s (post_only=%s)",
                so_id, config.direction, config.amount,
                config.instrument_name, initial_price, post_only,
            )
            self._emit("created", so)

        except DeribitAPIError as e:
            if e.code == 10041:  # post_only_reject
                so.state = SmartOrderState.FAILED
                logger.warning("SmartOrder %s: post_only_reject at %s", so_id, initial_price)
            else:
                so.state = SmartOrderState.FAILED
                logger.error("SmartOrder %s failed: %s", so_id, e)
            self._emit("failed", so)

        return so

    # ── Market data handlers ────────────────────────────────────────

    def _on_orderbook(self, channel: str, data: Any) -> None:
        instrument = channel.split(".")[1]
        builder = self._get_builder(instrument)
        builder.update_orderbook(data)
        self._process_orders(instrument)

    def _on_ticker(self, channel: str, data: Any) -> None:
        instrument = data.get("instrument_name", channel.split(".")[1])
        builder = self._get_builder(instrument)
        builder.update_ticker(data)

    def _process_orders(self, instrument: str) -> None:
        """Process all active SmartOrders for an instrument."""
        for so in list(self._orders.values()):
            if so.config.instrument_name != instrument:
                continue
            if so.state != SmartOrderState.ACTIVE:
                continue

            builder = self._get_builder(instrument)
            snapshot = builder.build(
                my_order=MyOrderState(
                    price=so.current_price,
                    amount=so.config.amount,
                    filled_amount=so.filled_amount,
                ),
                direction=so.config.direction,
                target_amount=so.config.amount,
                elapsed_ms=so.elapsed_ms,
                timeout_ms=so.config.timeout_ms,
                amend_count=so.amend_count,
                price_limit=so.config.price_limit,
                tick_size=so.tick_size,
                fee_context=so.fee_context,
            )

            action = so.algorithm.on_update(snapshot)
            self._handle_action(so, action)

    def _handle_action(self, so: SmartOrder, action: Action) -> None:
        if action.kind == "hold":
            return

        elif action.kind == "amend" and action.price is not None:
            new_price = self._snap_to_tick(action.price, so.tick_size)
            # Enforce price limit at engine level (algorithms cannot bypass)
            if so.config.price_limit is not None:
                if so.config.direction == "buy" and new_price > so.config.price_limit:
                    new_price = so.config.price_limit
                elif so.config.direction == "sell" and new_price < so.config.price_limit:
                    new_price = so.config.price_limit

            if new_price != so.current_price:
                self._throttle.enqueue(so.id, new_price, so.current_price)

        elif action.kind == "cancel":
            asyncio.create_task(self.cancel_smart_order(so.id))

        elif action.kind == "market":
            asyncio.create_task(self._convert_to_market(so))

    # ── Execution ───────────────────────────────────────────────────

    async def _execute_amend(self, so_id: str, new_price: float) -> None:
        """Execute an amend via the throttle."""
        so = self._orders.get(so_id)
        if not so or so.state != SmartOrderState.ACTIVE or not so.deribit_order_id:
            return

        try:
            remaining = so.config.amount - so.filled_amount
            order = await self._client.edit(so.deribit_order_id, remaining, new_price)
            so.current_price = new_price
            so.amend_count += 1
            so.deribit_order_id = order.order_id  # edit may return new order_id
            self._emit("amended", so)
        except DeribitAPIError as e:
            if e.code == 10041:  # post_only_reject
                logger.info("SmartOrder %s: post_only_reject at %s", so_id, new_price)
                # Algorithm will see this via next snapshot
            else:
                logger.warning("SmartOrder %s amend failed: %s", so_id, e)

    async def _convert_to_market(self, so: SmartOrder) -> None:
        """Cancel limit order and place market order."""
        if so.deribit_order_id:
            try:
                await self._client.cancel(so.deribit_order_id)
            except Exception:
                pass

        remaining = so.config.amount - so.filled_amount
        if remaining > 0:
            try:
                if so.config.direction == "buy":
                    await self._client.buy(
                        so.config.instrument_name, remaining, order_type="market"
                    )
                else:
                    await self._client.sell(
                        so.config.instrument_name, remaining, order_type="market"
                    )
                so.state = SmartOrderState.MARKET_FILLED
            except Exception as e:
                logger.error("SmartOrder %s market conversion failed: %s", so.id, e)
                so.state = SmartOrderState.FAILED
        else:
            so.state = SmartOrderState.COMPLETED

        self._emit("finished", so)

    # ── Manual intervention ─────────────────────────────────────────

    async def cancel_smart_order(self, so_id: str) -> SmartOrder | None:
        so = self._orders.get(so_id)
        if not so:
            return None

        if so.deribit_order_id and so.state == SmartOrderState.ACTIVE:
            try:
                await self._client.cancel(so.deribit_order_id)
            except Exception:
                pass

        so.state = SmartOrderState.CANCELLED
        self._emit("cancelled", so)
        return so

    def pause_all(self) -> int:
        """Pause all active SmartOrders. Returns count of paused orders."""
        count = 0
        for so in self._orders.values():
            if so.state == SmartOrderState.ACTIVE:
                so.state = SmartOrderState.PAUSED
                self._emit("paused", so)
                count += 1
        if count:
            logger.warning("SmartOrderEngine: paused %d active orders (risk trigger)", count)
        return count

    def pause_smart_order(self, so_id: str) -> SmartOrder | None:
        so = self._orders.get(so_id)
        if so and so.state == SmartOrderState.ACTIVE:
            so.state = SmartOrderState.PAUSED
            self._emit("paused", so)
        return so

    def resume_smart_order(self, so_id: str) -> SmartOrder | None:
        so = self._orders.get(so_id)
        if so and so.state == SmartOrderState.PAUSED:
            so.state = SmartOrderState.ACTIVE
            self._emit("resumed", so)
        return so

    async def market_smart_order(self, so_id: str) -> SmartOrder | None:
        so = self._orders.get(so_id)
        if so and so.state in (SmartOrderState.ACTIVE, SmartOrderState.PAUSED):
            await self._convert_to_market(so)
        return so

    # ── Order fill notification (called by OrderMonitor) ────────────

    def notify_fill(self, deribit_order_id: str, fill_price: float, fill_amount: float) -> None:
        """Called when an order fill is detected."""
        for so in self._orders.values():
            if so.deribit_order_id == deribit_order_id:
                so.filled_amount += fill_amount
                so.algorithm.on_fill(fill_price, fill_amount)

                if so.filled_amount >= so.config.amount:
                    so.state = SmartOrderState.COMPLETED
                    self._emit("completed", so)
                else:
                    self._emit("partial_fill", so)
                return

    def notify_order_cancelled(self, deribit_order_id: str) -> None:
        """Called when an order is cancelled externally."""
        for so in self._orders.values():
            if so.deribit_order_id == deribit_order_id and so.state == SmartOrderState.ACTIVE:
                so.state = SmartOrderState.CANCELLED
                self._emit("cancelled", so)
                return

    # ── Query ───────────────────────────────────────────────────────

    def list_orders(self, active_only: bool = True) -> list[SmartOrder]:
        if active_only:
            active_states = {SmartOrderState.ACTIVE, SmartOrderState.PAUSED, SmartOrderState.PENDING}
            return [so for so in self._orders.values() if so.state in active_states]
        return list(self._orders.values())

    def get_order(self, so_id: str) -> SmartOrder | None:
        return self._orders.get(so_id)

    # ── Internals ───────────────────────────────────────────────────

    def _get_builder(self, instrument: str) -> SnapshotBuilder:
        if instrument not in self._builders:
            self._builders[instrument] = SnapshotBuilder()
        return self._builders[instrument]

    async def _ensure_subscribed(self, instrument: str) -> None:
        if instrument in self._subscribed_instruments:
            return

        await self._client.subscribe(
            [f"book.{instrument}.100ms"],
            self._on_orderbook,
        )
        await self._client.subscribe(
            [f"ticker.{instrument}.raw"],
            self._on_ticker,
        )
        self._subscribed_instruments.add(instrument)

    @staticmethod
    def _snap_to_tick(price: float, tick_size: float) -> float:
        return round(price / tick_size) * tick_size

    def _emit(self, event: str, so: SmartOrder) -> None:
        data = {"event": event, **so.to_dict()}
        for cb in self._event_callbacks:
            result = cb(so.id, data)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
