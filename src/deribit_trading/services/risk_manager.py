"""RiskManager: multi-dimensional risk controls for trading."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .portfolio import PortfolioService
    from ..smart_order.engine import SmartOrderEngine

logger = logging.getLogger(__name__)


class RiskLimitError(Exception):
    """Raised when a risk limit is breached."""

    def __init__(self, limit_name: str, message: str) -> None:
        self.limit_name = limit_name
        super().__init__(f"Risk limit '{limit_name}': {message}")


@dataclass
class RiskConfig:
    """Runtime-configurable risk limits."""

    max_order_size_usd: float = 100_000
    max_position_size: float = 10.0  # per instrument, in base currency
    daily_loss_limit_usd: float = 5_000
    max_total_delta: float = 5.0  # absolute value
    margin_alert_threshold: float = 0.8  # initial_margin / equity


class RiskManager:
    """Multi-dimensional risk checker integrated into the trading pipeline."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self._daily_pnl: float = 0.0
        self._trading_paused: bool = False
        self._last_reset_date: date = datetime.now(timezone.utc).date()
        self._portfolio_service: PortfolioService | None = None
        self._smart_engine: SmartOrderEngine | None = None
        self._periodic_task: asyncio.Task[None] | None = None

    @property
    def trading_paused(self) -> bool:
        return self._trading_paused

    def set_portfolio_service(self, svc: PortfolioService) -> None:
        self._portfolio_service = svc

    def set_smart_engine(self, engine: SmartOrderEngine) -> None:
        self._smart_engine = engine

    # ── Pre-trade check ─────────────────────────────────────────────

    def check(
        self,
        instrument_name: str,
        direction: str,
        amount: float,
        price: float | None = None,
    ) -> None:
        """Check risk limits before placing an order. Raises RiskLimitError if breached."""
        self._maybe_reset_daily()

        if self._trading_paused:
            raise RiskLimitError(
                "trading_paused",
                f"Trading paused due to daily loss limit (loss: ${self._daily_pnl:.2f})",
            )

        # Order size check
        # For inverse contracts (BTC-PERPETUAL), amount is already in USD
        # For linear/options, amount * price approximates USD value
        if price is not None and price > 0:
            # Heuristic: if price > 1000, it's likely an inverse contract where amount = USD
            order_usd = amount if price > 1000 else amount * price
            if order_usd > self.config.max_order_size_usd:
                raise RiskLimitError(
                    "max_order_size",
                    f"Order ${order_usd:.0f} exceeds limit ${self.config.max_order_size_usd:.0f}",
                )

    # ── PnL tracking ────────────────────────────────────────────────

    def update_pnl(self, pnl_change: float) -> None:
        """Update daily PnL. Called on portfolio updates."""
        self._maybe_reset_daily()
        self._daily_pnl += pnl_change

        if self._daily_pnl < -self.config.daily_loss_limit_usd:
            if not self._trading_paused:
                self._trading_paused = True
                logger.warning(
                    "RISK: Daily loss limit breached (loss: $%.2f, limit: $%.2f). Trading paused.",
                    abs(self._daily_pnl),
                    self.config.daily_loss_limit_usd,
                )
                # Pause all smart orders
                if self._smart_engine:
                    self._smart_engine.pause_all()

    # ── Periodic checks ────────────────────────────────────────────

    async def start_periodic_check(self, interval_seconds: float = 30) -> None:
        """Start periodic risk monitoring (delta, margin)."""
        self._periodic_task = asyncio.create_task(
            self._periodic_loop(interval_seconds)
        )

    async def stop_periodic_check(self) -> None:
        if self._periodic_task and not self._periodic_task.done():
            self._periodic_task.cancel()
            try:
                await self._periodic_task
            except asyncio.CancelledError:
                pass

    async def _periodic_loop(self, interval: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await self.periodic_check()
        except asyncio.CancelledError:
            pass

    async def periodic_check(self) -> None:
        """Check delta exposure and margin usage."""
        if not self._portfolio_service:
            return

        try:
            # Delta check
            greeks = await self._portfolio_service.get_greeks_summary("BTC")
            if abs(greeks.net_delta) > self.config.max_total_delta:
                logger.warning(
                    "RISK: Delta exposure %.2f exceeds limit %.2f",
                    greeks.net_delta,
                    self.config.max_total_delta,
                )

            # Margin check
            from ..client import DeribitClient
            account = await self._portfolio_service._client.get_account_summary("BTC")
            if account.equity > 0:
                margin_usage = account.initial_margin / account.equity
                if margin_usage > self.config.margin_alert_threshold:
                    logger.warning(
                        "RISK: Margin usage %.1f%% exceeds threshold %.1f%%",
                        margin_usage * 100,
                        self.config.margin_alert_threshold * 100,
                    )
        except Exception as e:
            logger.warning("Risk periodic check failed: %s", e)

    # ── Manual controls ─────────────────────────────────────────────

    def resume_trading(self) -> None:
        """Manually resume trading after a pause."""
        self._trading_paused = False
        logger.info("RISK: Trading resumed manually")

    def update_config(self, **kwargs: Any) -> None:
        """Update risk config at runtime."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info("Risk config updated: %s = %s", key, value)

    # ── Status ──────────────────────────────────────────────────────

    def get_risk_status(self) -> dict[str, Any]:
        return {
            "daily_pnl": self._daily_pnl,
            "trading_paused": self._trading_paused,
            "last_reset_date": str(self._last_reset_date),
            "config": {
                "max_order_size_usd": self.config.max_order_size_usd,
                "max_position_size": self.config.max_position_size,
                "daily_loss_limit_usd": self.config.daily_loss_limit_usd,
                "max_total_delta": self.config.max_total_delta,
                "margin_alert_threshold": self.config.margin_alert_threshold,
            },
        }

    # ── Internal ────────────────────────────────────────────────────

    def _maybe_reset_daily(self) -> None:
        """Reset daily PnL counter at UTC midnight."""
        today = datetime.now(timezone.utc).date()
        if today > self._last_reset_date:
            self._daily_pnl = 0.0
            self._last_reset_date = today
            if self._trading_paused:
                logger.info("RISK: Daily PnL reset. Trading still paused (manual resume required).")
