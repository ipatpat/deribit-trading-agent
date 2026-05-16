"""Portfolio service for equity tracking, Greeks aggregation, and PnL attribution."""

import asyncio
import logging
import time
from typing import Any

from ..client import DeribitClient
from ..config import EnvManager
from ..config.account_manager import AccountManager
from ..models import AccountSummary, GreeksSummary, Position, PortfolioSnapshot
from ..persistence import (
    Database,
    EquitySnapshotRepo,
    PositionHistoryRepo,
    auto_bucket_ms,
    get_equity_bucketed,
)

logger = logging.getLogger(__name__)

DEFAULT_GAP_THRESHOLD_MS = 30 * 60 * 1000  # 30 minutes


class PortfolioService:
    """Monitors portfolio, tracks equity curve, aggregates Greeks."""

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
        self._equity_repo = EquitySnapshotRepo(db)
        self._position_repo = PositionHistoryRepo(db)
        self._db = db
        self._tracking = False

    def _current_account_id(self) -> str:
        """Resolve the active account UUID for per-account writes/reads.

        Falls back to env_manager's env string for unit tests and pre-bootstrap
        callers where account_manager isn't wired."""
        if self._account_manager and self._account_manager.active_id:
            return self._account_manager.active_id
        return self._env.current_env

    async def reset_cache(self) -> None:
        """Forget all per-account state so the next start_tracking call
        re-subscribes from scratch. Used during account switch."""
        if hasattr(self, '_tracking_currencies'):
            self._tracking_currencies.clear()
        self._tracking = False
        logger.info("PortfolioService cache reset")

    async def start_tracking(self, currency: str = "BTC") -> None:
        """Subscribe to portfolio updates and record all data."""
        if not hasattr(self, '_tracking_currencies'):
            self._tracking_currencies: set[str] = set()

        if currency in self._tracking_currencies:
            return

        channel = f"user.portfolio.{currency.lower()}"

        async def _on_portfolio(ch: str, data: Any) -> None:
            await self._record_snapshot(data)

        await self._client.subscribe([channel], _on_portfolio)
        self._tracking_currencies.add(currency)
        self._tracking = True
        logger.info("Portfolio tracking started for %s", currency)

    async def _record_snapshot(self, data: dict[str, Any]) -> None:
        """Write a portfolio update to the database."""
        ts = data.get("creation_timestamp") or int(time.time() * 1000)
        await self._equity_repo.save(
            timestamp=ts,
            account_id=self._current_account_id(),
            currency=data.get("currency", ""),
            equity=data.get("equity", 0),
            balance=data.get("balance", 0),
            margin_balance=data.get("margin_balance", 0),
            unrealized_pnl=data.get("session_upl", 0),
            realized_pnl=data.get("session_rpl", 0),
        )

    async def get_equity_curve(
        self,
        currency: str,
        since: int,
        until: int,
        max_points: int = 1000,
        gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    ) -> dict[str, Any]:
        """Get equity curve data with automatic bucketing and gap detection.

        Returns:
            Dict with 'data' (bucketed time series) and 'gaps' (offline intervals).
        """
        account_id = self._current_account_id()
        bucket_ms = auto_bucket_ms(since, until, max_points)

        data = await get_equity_bucketed(self._db, account_id, currency, since, until, bucket_ms)

        # Detect gaps (offline intervals)
        gaps: list[dict[str, int]] = []
        for i in range(1, len(data)):
            prev_time = data[i - 1]["bucket_time"]
            curr_time = data[i]["bucket_time"]
            if curr_time - prev_time > gap_threshold_ms:
                gaps.append({"start": prev_time, "end": curr_time})

        return {
            "data": data,
            "gaps": gaps,
            "bucket_ms": bucket_ms,
            "total_raw_points": sum(d["point_count"] for d in data),
        }

    async def get_snapshot(self, currency: str) -> PortfolioSnapshot:
        """Get current portfolio snapshot with all positions and Greeks."""
        # Use extended=True to get delta_total and options greeks from Deribit directly
        account, positions = await asyncio.gather(
            self._client.get_account_summary(currency),
            self._client.get_positions(currency),
        )

        # Use Deribit's pre-calculated greeks when available
        greeks = GreeksSummary(
            net_delta=account.delta_total or 0.0,
            net_gamma=account.options_gamma or 0.0,
            net_theta=account.options_theta or 0.0,
            net_vega=account.options_vega or 0.0,
        )

        return PortfolioSnapshot(
            timestamp=int(time.time() * 1000),
            currency=currency,
            equity=account.equity,
            balance=account.balance,
            unrealized_pnl=account.session_upl,
            realized_pnl=account.session_rpl,
            positions=positions,
            greeks_summary=greeks,
        )

    async def get_greeks_summary(self, currency: str) -> GreeksSummary:
        """Get aggregated Greeks across all positions."""
        positions = await self._client.get_positions(currency)
        return self._aggregate_greeks(positions)

    async def get_pnl_attribution(self, currency: str) -> list[dict[str, Any]]:
        """Get PnL broken down by instrument, sorted by contribution.

        Skips net-zero / closed positions (size == 0, direction == 'zero').
        """
        positions = await self._client.get_positions(currency)
        attribution = [
            {
                "instrument": p.instrument_name,
                "direction": p.direction,
                "size": p.size,
                "realized_pnl": p.realized_profit_loss,
                "unrealized_pnl": p.floating_profit_loss,
                "total_pnl": p.total_profit_loss,
            }
            for p in positions
            if p.size > 0
        ]
        attribution.sort(key=lambda x: abs(x["total_pnl"]), reverse=True)
        return attribution

    async def save_position_snapshot(self, currency: str) -> None:
        """Save current positions to history for later analysis."""
        positions = await self._client.get_positions(currency)
        pos_dicts = [
            {
                "instrument_name": p.instrument_name,
                "direction": p.direction,
                "size": p.size,
                "average_price": p.average_price,
                "mark_price": p.mark_price,
                "floating_profit_loss": p.floating_profit_loss,
                "delta": p.delta,
                "gamma": p.gamma,
                "theta": p.theta,
                "vega": p.vega,
            }
            for p in positions
        ]
        await self._position_repo.save_snapshot(
            timestamp=int(time.time() * 1000),
            account_id=self._current_account_id(),
            positions=pos_dicts,
        )

    @staticmethod
    def _aggregate_greeks(positions: list[Position]) -> GreeksSummary:
        net_delta = 0.0
        net_gamma = 0.0
        net_theta = 0.0
        net_vega = 0.0

        for p in positions:
            if p.delta is not None:
                net_delta += p.delta
            elif p.kind == "future":
                # Futures have delta = size * direction
                sign = 1.0 if p.direction == "buy" else -1.0
                net_delta += p.size * sign
            if p.gamma is not None:
                net_gamma += p.gamma
            if p.theta is not None:
                net_theta += p.theta
            if p.vega is not None:
                net_vega += p.vega

        return GreeksSummary(
            net_delta=net_delta,
            net_gamma=net_gamma,
            net_theta=net_theta,
            net_vega=net_vega,
        )
