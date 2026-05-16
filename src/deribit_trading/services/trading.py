"""Trading service for order management and position control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..client import DeribitClient
from ..config import EnvManager
from ..models import Order, OrderType, Position, TimeInForce, Trade, TriggerType
from ..persistence import Database, OrderRepo, TradeRepo

if TYPE_CHECKING:
    from ..config.account_manager import AccountManager
    from ..smart_order.engine import SmartOrder, SmartOrderEngine
    from ..smart_order.types import SmartOrderConfig
    from .risk_manager import RiskManager


class TradingService:
    """Handles order placement, modification, cancellation, and position management."""

    def __init__(
        self,
        client: DeribitClient,
        env_manager: EnvManager,
        db: Database,
        account_manager: AccountManager | None = None,
    ) -> None:
        self._client = client
        self._env = env_manager
        self._account_manager = account_manager
        self._order_repo = OrderRepo(db)
        self._trade_repo = TradeRepo(db)
        self._risk_manager: RiskManager | None = None

    def _current_account_id(self) -> str:
        if self._account_manager and self._account_manager.active_id:
            return self._account_manager.active_id
        return self._env.current_env

    def set_risk_manager(self, rm: RiskManager) -> None:
        self._risk_manager = rm

    def _check_risk(self, instrument_name: str, direction: str, amount: float, price: float | None) -> None:
        if self._risk_manager:
            self._risk_manager.check(instrument_name, direction, amount, price)

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
        self._env.check_trading_allowed()
        self._check_risk(instrument_name, "buy", amount, price)
        order = await self._client.buy(
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
        await self._persist_order(order)
        return order

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
        self._env.check_trading_allowed()
        self._check_risk(instrument_name, "sell", amount, price)
        order = await self._client.sell(
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
        await self._persist_order(order)
        return order

    async def edit(self, order_id: str, amount: float, price: float) -> Order:
        self._env.check_trading_allowed()
        order = await self._client.edit(order_id, amount, price)
        await self._persist_order(order)
        return order

    async def cancel(self, order_id: str) -> Order:
        order = await self._client.cancel(order_id)
        await self._persist_order(order)
        return order

    async def cancel_all(
        self,
        currency: str | None = None,
        instrument_name: str | None = None,
    ) -> int:
        return await self._client.cancel_all(currency, instrument_name)

    async def get_positions(self, currency: str) -> list[Position]:
        return await self._client.get_positions(currency)

    async def close_position(
        self,
        instrument_name: str,
        order_type: OrderType = OrderType.MARKET,
    ) -> Order:
        self._env.check_trading_allowed()
        order = await self._client.close_position(instrument_name, order_type)
        await self._persist_order(order)
        return order

    async def get_open_orders(
        self,
        currency: str | None = None,
        instrument_name: str | None = None,
    ) -> list[Order]:
        return await self._client.get_open_orders(currency, instrument_name)

    async def get_order_state(self, order_id: str) -> Order:
        return await self._client.get_order_state(order_id)

    async def get_user_trades(self, currency: str, count: int = 100) -> list[Trade]:
        trades = await self._client.get_user_trades(currency, count)
        for t in trades:
            await self._persist_trade(t)
        return trades

    async def enable_cancel_on_disconnect(self) -> None:
        await self._client.enable_cancel_on_disconnect()

    # ── Smart orders ────────────────────────────────────────────────

    def set_smart_engine(self, engine: SmartOrderEngine) -> None:
        self._smart_engine = engine

    async def smart_buy(
        self,
        instrument_name: str,
        amount: float,
        algorithm: str = "tick-chaser",
        price_limit: float | None = None,
        timeout_ms: int | None = 120_000,
        patience: float = 0.5,
    ) -> SmartOrder:
        self._env.check_trading_allowed()
        from ..smart_order.types import SmartOrderConfig
        config = SmartOrderConfig(
            instrument_name=instrument_name,
            direction="buy",
            amount=amount,
            algorithm=algorithm,
            price_limit=price_limit,
            timeout_ms=timeout_ms,
            patience=patience,
        )
        return await self._smart_engine.create_smart_order(config)

    async def smart_sell(
        self,
        instrument_name: str,
        amount: float,
        algorithm: str = "tick-chaser",
        price_limit: float | None = None,
        timeout_ms: int | None = 120_000,
        patience: float = 0.5,
    ) -> SmartOrder:
        self._env.check_trading_allowed()
        from ..smart_order.types import SmartOrderConfig
        config = SmartOrderConfig(
            instrument_name=instrument_name,
            direction="sell",
            amount=amount,
            algorithm=algorithm,
            price_limit=price_limit,
            timeout_ms=timeout_ms,
            patience=patience,
        )
        return await self._smart_engine.create_smart_order(config)

    async def _persist_order(self, order: Order) -> None:
        await self._order_repo.save(
            order_id=order.order_id,
            account_id=self._current_account_id(),
            timestamp=order.creation_timestamp,
            instrument_name=order.instrument_name,
            direction=order.direction,
            order_type=order.order_type,
            price=order.price,
            amount=order.amount,
            filled_amount=order.filled_amount,
            order_state=order.order_state,
            label=order.label,
        )

    async def _persist_trade(self, trade: Trade) -> None:
        await self._trade_repo.save(
            trade_id=trade.trade_id,
            account_id=self._current_account_id(),
            timestamp=trade.timestamp,
            instrument_name=trade.instrument_name,
            direction=trade.direction,
            price=trade.price,
            amount=trade.amount,
            fee=trade.fee,
            fee_currency=trade.fee_currency,
            pnl=trade.profit_loss,
            order_id=trade.order_id,
            label=trade.label,
        )
