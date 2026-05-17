"""SmartOrderEngine: manages multiple SmartOrders with event-driven updates.

Intent-only routing: every SmartOrder is dispatched to `StandardIntent` or
`UrgentIntent` via `config.intent`. There is no legacy algorithm path.
"""

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
from .fee_logic import build_fee_context
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

SmartOrderCallback = (
    Callable[[str, dict[str, Any]], None]
    | Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
)


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
    arrival_mid: float = 0.0
    current_level: int = 0  # 0-4: Lv0..Lv4 (Lv0=own-top, Lv4=market)
    post_only_reject_count: int = 0
    # Populated when state transitions to FAILED. Surfaces the underlying
    # exchange error (incl. DeribitAPIError.data.reason / .param) so the
    # caller — REST client, MCP agent, UI — can self-correct without
    # consulting the server log.
    last_error: str | None = None

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.created_at) * 1000)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "instrument": self.config.instrument_name,
            "direction": self.config.direction,
            "amount": self.config.amount,
            "intent": self.config.intent,
            "state": self.state,
            "deribit_order_id": self.deribit_order_id,
            "current_price": self.current_price,
            "current_level": self.current_level,
            "filled_amount": self.filled_amount,
            "amend_count": self.amend_count,
            "post_only_reject_count": self.post_only_reject_count,
            "elapsed_ms": self.elapsed_ms,
            "t_patience_ms": self.config.t_patience_ms,
            "fee_mode": "maker" if self.fee_context.is_post_only else "any",
        }
        if self.last_error is not None:
            d["last_error"] = self.last_error
        return d


class SmartOrderEngine:
    """Manages multiple SmartOrders with event-driven market data updates."""

    def __init__(self, client: DeribitClient) -> None:
        self._client = client
        self._orders: dict[str, SmartOrder] = {}
        self._builders: dict[str, SnapshotBuilder] = {}
        self._subscribed_instruments: set[str] = set()
        self._throttle = AmendThrottle()
        self._throttle.set_executor(self._execute_amend)
        self._event_callbacks: list[SmartOrderCallback] = []
        self._risk_manager: Any = None

    def set_risk_manager(self, rm: Any) -> None:
        self._risk_manager = rm

    async def start(self) -> None:
        await self._throttle.start()

    async def stop(self) -> None:
        await self._throttle.stop()
        for so in list(self._orders.values()):
            if so.state == SmartOrderState.ACTIVE:
                await self.cancel_smart_order(so.id)

    async def reset(self) -> None:
        """Drop all client-side smart-order state without touching Deribit.

        Used during account switch: the new account has no relationship to
        the previous account's in-flight smart orders, so we forget them
        locally. The orders they spawned on Deribit remain on the exchange
        for the previous account's owner to handle (e.g. by switching back).
        """
        await self._throttle.stop()
        self._orders.clear()
        logger.info("SmartOrderEngine reset (forgot all client-side state)")
        await self._throttle.start()

    def on_event(self, callback: SmartOrderCallback) -> None:
        self._event_callbacks.append(callback)

    # ── Create SmartOrder ───────────────────────────────────────────

    async def create_smart_order(self, config: SmartOrderConfig) -> SmartOrder:
        """Create and start a new SmartOrder.

        Routes by `config.intent`: "standard" → intent:standard,
        "urgent" → intent:urgent.
        """
        if self._risk_manager:
            self._risk_manager.check(
                config.instrument_name, config.direction,
                config.amount, None,
            )

        so_id = f"so-{uuid.uuid4().hex[:8]}"
        fee_ctx = build_fee_context(config.instrument_name)
        if not config.prefer_maker:
            fee_ctx = FeeContext(
                maker_fee=fee_ctx.maker_fee,
                taker_fee=fee_ctx.taker_fee,
                is_post_only=False,
                instrument_type=fee_ctx.instrument_type,
            )

        # Resolve algorithm by intent
        algo_name, algo_params = self._resolve_algorithm(config)
        algo = get_algorithm(algo_name, algo_params)
        algo.attach_config(config)

        # Tick size
        tick_size = await self._fetch_tick_size(config.instrument_name)

        # Get / create builder
        builder = self._get_builder(config.instrument_name)

        # Subscribe and warm up market data
        await self._ensure_subscribed(config.instrument_name)
        try:
            ob = await self._client.get_order_book(config.instrument_name, depth=10)
            builder.update_orderbook(ob)
            ticker_data = await self._client.call(
                "public/ticker", {"instrument_name": config.instrument_name}
            )
            builder.update_ticker(ticker_data)
        except Exception as e:
            logger.warning("SmartOrder %s: failed to fetch initial data: %s", so_id, e)

        # Capture arrival_mid before placement
        arrival_mid = builder._build_orderbook().mid_price

        so = SmartOrder(
            id=so_id, config=config, algorithm=algo, fee_context=fee_ctx,
            tick_size=tick_size, arrival_mid=arrival_mid,
        )
        self._orders[so_id] = so

        # Build initial snapshot and decide initial action by intent
        snapshot = self._build_snapshot(so)
        initial_price = algo.initial_price(snapshot)

        if config.intent == "urgent":
            # Urgent: fire IOC immediately. _place_ioc + _convert_to_market manage level.
            await self._place_ioc(so, price=initial_price, amount=config.amount)
            return so

        # Standard: place limit at Lv0 with post_only (unless escape hatch)
        try:
            await self._place_limit(
                so, price=self._snap_to_tick(initial_price, tick_size),
                post_only=so.config.prefer_maker,
            )
            so.current_level = 0
        except DeribitAPIError as e:
            if e.code == 10041:
                # post_only reject → use algo recovery
                await self._handle_post_only_reject(so)
            else:
                so.state = SmartOrderState.FAILED
                so.last_error = str(e)
                logger.error("SmartOrder %s failed: %s", so_id, e)
                self._emit("failed", so)

        return so

    def _resolve_algorithm(self, config: SmartOrderConfig) -> tuple[str, dict]:
        params = {
            "t_patience_ms": config.t_patience_ms,
            "max_cross_levels": config.max_cross_levels,
        }
        return f"intent:{config.intent}", params

    # ── Snapshot construction ───────────────────────────────────────

    def _build_snapshot(self, so: SmartOrder):
        builder = self._get_builder(so.config.instrument_name)
        return builder.build(
            my_order=MyOrderState(
                price=so.current_price,
                amount=so.config.amount,
                filled_amount=so.filled_amount,
                current_level=so.current_level,
                post_only_reject_count=so.post_only_reject_count,
            ),
            direction=so.config.direction,
            target_amount=so.config.amount,
            elapsed_ms=so.elapsed_ms,
            timeout_ms=None,
            amend_count=so.amend_count,
            price_limit=None,
            tick_size=so.tick_size,
            fee_context=so.fee_context,
            arrival_mid=so.arrival_mid,
        )

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
        for so in list(self._orders.values()):
            if so.config.instrument_name != instrument:
                continue
            if so.state != SmartOrderState.ACTIVE:
                continue  # skip ESCALATING/PAUSED/etc.

            snapshot = self._build_snapshot(so)
            action = so.algorithm.on_update(snapshot)
            self._handle_action(so, action)

    def _handle_action(self, so: SmartOrder, action: Action) -> None:
        kind = action.kind
        if kind == "hold":
            return

        if kind == "amend" and action.price is not None:
            new_price = self._snap_to_tick(action.price, so.tick_size)
            if new_price != so.current_price:
                self._throttle.enqueue(
                    so.id, new_price, so.current_price, post_only=action.post_only,
                )
            return

        if kind == "place" and action.price is not None:
            new_price = self._snap_to_tick(action.price, so.tick_size)
            asyncio.create_task(
                self._place_limit(so, price=new_price, post_only=action.post_only)
            )
            return

        if kind == "ioc" and action.price is not None:
            asyncio.create_task(
                self._place_ioc(so, price=action.price, amount=action.amount or so.config.amount)
            )
            return

        if kind == "cancel":
            asyncio.create_task(self.cancel_smart_order(so.id))
            return

        if kind == "market":
            asyncio.create_task(self._convert_to_market(so))
            return

    # ── Order placement helpers ─────────────────────────────────────

    async def _place_limit(self, so: SmartOrder, price: float, post_only: bool) -> None:
        """Place an initial limit order or re-place after recovery."""
        try:
            if so.config.direction == "buy":
                order = await self._client.buy(
                    instrument_name=so.config.instrument_name,
                    amount=so.config.amount - so.filled_amount,
                    order_type="limit",
                    price=price,
                    post_only=post_only,
                )
            else:
                order = await self._client.sell(
                    instrument_name=so.config.instrument_name,
                    amount=so.config.amount - so.filled_amount,
                    order_type="limit",
                    price=price,
                    post_only=post_only,
                )
            so.deribit_order_id = order.order_id
            so.current_price = price
            so.state = SmartOrderState.ACTIVE
            logger.info(
                "SmartOrder %s placed: %s %s @ %s (post_only=%s, level=%s)",
                so.id, so.config.direction, so.config.amount,
                price, post_only, so.current_level,
            )
            self._emit("placed", so)
        except DeribitAPIError as e:
            if e.code == 10041:
                logger.info("SmartOrder %s: post_only_reject at place (price=%s)", so.id, price)
                await self._handle_post_only_reject(so)
            else:
                so.state = SmartOrderState.FAILED
                so.last_error = str(e)
                logger.error("SmartOrder %s place failed: %s", so.id, e)
                self._emit("failed", so)

    async def _place_ioc(self, so: SmartOrder, price: float, amount: float) -> None:
        """Fire IOC sweep at Lv3."""
        so.state = SmartOrderState.ESCALATING
        so.current_level = 3
        try:
            buy_or_sell = self._client.buy if so.config.direction == "buy" else self._client.sell
            order = await buy_or_sell(
                instrument_name=so.config.instrument_name,
                amount=amount,
                order_type="limit",
                price=self._snap_to_tick(price, so.tick_size),
                post_only=False,
                time_in_force="immediate_or_cancel",
            )
            filled = float(getattr(order, "filled_amount", 0) or 0)
            if filled > 0:
                so.filled_amount += filled
                so.algorithm.on_fill(price, filled)
                self._emit("partial_fill", so)
            remaining = so.config.amount - so.filled_amount
            if remaining > 0:
                # Lv4 market for residual
                await self._convert_to_market(so)
            else:
                so.state = SmartOrderState.COMPLETED
                self._emit("completed", so)
        except DeribitAPIError as e:
            logger.error("SmartOrder %s IOC failed: %s", so.id, e)
            so.state = SmartOrderState.FAILED
            so.last_error = str(e)
            self._emit("failed", so)

    async def _handle_post_only_reject(self, so: SmartOrder) -> None:
        """Recovery path: ask algorithm what to do, dispatch action."""
        so.post_only_reject_count += 1
        if not self._throttle.can_enqueue_recovery(so.id):
            logger.warning("SmartOrder %s: post_only thrash → escalate", so.id)
            # Force escalate: market
            await self._convert_to_market(so)
            return

        self._throttle.record_recovery(so.id)
        algo = so.algorithm
        on_reject = getattr(algo, "on_post_only_reject", None)
        if not callable(on_reject):
            so.state = SmartOrderState.FAILED
            so.last_error = "algorithm does not implement on_post_only_reject"
            self._emit("failed", so)
            return
        snapshot = self._build_snapshot(so)
        action = on_reject(snapshot)
        self._handle_action(so, action)

    # ── Execution (throttle executor) ───────────────────────────────

    async def _execute_amend(self, so_id: str, new_price: float, post_only: bool) -> None:
        so = self._orders.get(so_id)
        if not so or so.state != SmartOrderState.ACTIVE or not so.deribit_order_id:
            return

        # Detect level transition: if post_only flipped from prev or price crosses,
        # mark ESCALATING transiently.
        try:
            remaining = so.config.amount - so.filled_amount
            order = await self._client.edit(
                so.deribit_order_id, remaining, new_price, post_only=post_only,
            )
            so.current_price = new_price
            so.amend_count += 1
            # current_level inferred by algorithm; engine tracks via my_order. We'll
            # rely on algorithm to drive level transitions through post_only flag.
            so.deribit_order_id = order.order_id
            self._emit("amended", so)
        except DeribitAPIError as e:
            if e.code == 10041:
                logger.info("SmartOrder %s: post_only_reject on amend at %s", so_id, new_price)
                await self._handle_post_only_reject(so)
            else:
                logger.warning("SmartOrder %s amend failed: %s", so_id, e)
        except TypeError:
            # client.edit may not accept post_only kwarg; retry without
            try:
                remaining = so.config.amount - so.filled_amount
                order = await self._client.edit(so.deribit_order_id, remaining, new_price)
                so.current_price = new_price
                so.amend_count += 1
                so.deribit_order_id = order.order_id
                self._emit("amended", so)
            except DeribitAPIError as e2:
                if e2.code == 10041:
                    await self._handle_post_only_reject(so)
                else:
                    logger.warning("SmartOrder %s amend failed: %s", so_id, e2)

    async def _convert_to_market(self, so: SmartOrder) -> None:
        if so.deribit_order_id:
            try:
                await self._client.cancel(so.deribit_order_id)
            except Exception:
                pass

        remaining = so.config.amount - so.filled_amount
        so.current_level = 4
        if remaining > 0:
            try:
                buy_or_sell = self._client.buy if so.config.direction == "buy" else self._client.sell
                await buy_or_sell(
                    so.config.instrument_name, remaining, order_type="market",
                )
                so.state = SmartOrderState.MARKET_FILLED
            except Exception as e:
                logger.error("SmartOrder %s market conversion failed: %s", so.id, e)
                so.state = SmartOrderState.FAILED
                so.last_error = f"market conversion failed: {e}"
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

    # ── Order fill notification ─────────────────────────────────────

    def notify_fill(self, deribit_order_id: str, fill_price: float, fill_amount: float) -> None:
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
        for so in self._orders.values():
            if so.deribit_order_id == deribit_order_id and so.state == SmartOrderState.ACTIVE:
                so.state = SmartOrderState.CANCELLED
                self._emit("cancelled", so)
                return

    # ── Query ───────────────────────────────────────────────────────

    def list_orders(self, active_only: bool = True) -> list[SmartOrder]:
        if active_only:
            active_states = {
                SmartOrderState.ACTIVE,
                SmartOrderState.PAUSED,
                SmartOrderState.PENDING,
                SmartOrderState.ESCALATING,
            }
            return [so for so in self._orders.values() if so.state in active_states]
        return list(self._orders.values())

    def get_order(self, so_id: str) -> SmartOrder | None:
        return self._orders.get(so_id)

    # ── Internals ───────────────────────────────────────────────────

    def _get_builder(self, instrument: str) -> SnapshotBuilder:
        if instrument not in self._builders:
            self._builders[instrument] = SnapshotBuilder(instrument_name=instrument)
        return self._builders[instrument]

    async def _ensure_subscribed(self, instrument: str) -> None:
        if instrument in self._subscribed_instruments:
            return
        # Use the grouped/depth-limited book channel: returns full snapshots
        # in `[[price, size], ...]` form. The plain `book.{inst}.{interval}`
        # channel emits incremental deltas (`[[action, price, size]]`) which
        # SnapshotBuilder doesn't reconstruct.
        await self._client.subscribe(
            [f"book.{instrument}.none.10.100ms"], self._on_orderbook,
        )
        await self._client.subscribe(
            [f"ticker.{instrument}.raw"], self._on_ticker,
        )
        self._subscribed_instruments.add(instrument)

    async def _fetch_tick_size(self, instrument_name: str) -> float:
        try:
            instruments = await self._client.get_instruments(
                instrument_name.split("-")[0]
            )
            for inst in instruments:
                if inst.instrument_name == instrument_name:
                    return inst.tick_size
        except Exception:
            pass
        return 0.5

    @staticmethod
    def _snap_to_tick(price: float, tick_size: float) -> float:
        return round(price / tick_size) * tick_size

    _TERMINAL_STATES = (
        SmartOrderState.COMPLETED,
        SmartOrderState.CANCELLED,
        SmartOrderState.MARKET_FILLED,
        SmartOrderState.FAILED,
    )

    def _emit(self, event: str, so: SmartOrder) -> None:
        data = {"event": event, **so.to_dict()}
        for cb in self._event_callbacks:
            result = cb(so.id, data)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        if so.state in self._TERMINAL_STATES and not getattr(so, "_terminal_logged", False):
            so._terminal_logged = True  # type: ignore[attr-defined]
            self._log_terminal(so)

    def _log_terminal(self, so: SmartOrder) -> None:
        """One-line structured log per SmartOrder terminal state for offline tuning.

        Covers the metrics needed to retune σ_min/σ_max/t_patience_ms after rollout
        without a separate baseline-collection script.
        """
        target = so.config.amount or 0.0
        fill_ratio = so.filled_amount / target if target > 0 else 0.0
        # maker_ratio: 1.0 if filled at Lv0/Lv1 (post_only), 0.0 if Lv3/Lv4 (taker), 0.5 ambiguous
        if so.current_level <= 1:
            maker_ratio = 1.0
        elif so.current_level >= 3:
            maker_ratio = 0.0
        else:
            maker_ratio = 0.5  # Lv2 is opposite-top, depends on which side filled
        sigma = 0.0
        try:
            builder = self._builders.get(so.config.instrument_name)
            if builder is not None:
                tracker = getattr(builder, "_sigma_tracker", None) or getattr(builder, "sigma_tracker", None)
                if tracker is not None:
                    sigma = float(getattr(tracker, "sigma", 0.0))
        except Exception:
            pass
        logger.info(
            "smart_order_terminal so_id=%s instrument=%s direction=%s intent=%s "
            "state=%s current_level=%d elapsed_ms=%d sigma=%.6f "
            "post_only_reject_count=%d fill_ratio=%.4f maker_ratio=%.2f",
            so.id,
            so.config.instrument_name,
            so.config.direction,
            so.config.intent,
            so.state.value if hasattr(so.state, "value") else so.state,
            so.current_level,
            so.elapsed_ms,
            sigma,
            so.post_only_reject_count,
            fill_ratio,
            maker_ratio,
        )
