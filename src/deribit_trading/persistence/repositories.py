"""Repository classes for database CRUD operations."""

from typing import Any

import aiosqlite

from .database import Database


class EquitySnapshotRepo:
    """CRUD for equity_snapshots table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self,
        timestamp: int,
        env: str,
        currency: str,
        equity: float,
        balance: float,
        margin_balance: float = 0.0,
        unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0,
    ) -> None:
        await self._db.connection.execute(
            """INSERT INTO equity_snapshots
               (timestamp, env, currency, equity, balance, margin_balance, unrealized_pnl, realized_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, env, currency, equity, balance, margin_balance, unrealized_pnl, realized_pnl),
        )
        await self._db.connection.commit()

    async def get_range(
        self,
        env: str,
        currency: str,
        since: int,
        until: int,
    ) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            """SELECT timestamp, equity, balance, margin_balance, unrealized_pnl, realized_pnl
               FROM equity_snapshots
               WHERE env = ? AND currency = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (env, currency, since, until),
        )
        rows = await cursor.fetchall()
        return [
            {
                "timestamp": r[0],
                "equity": r[1],
                "balance": r[2],
                "margin_balance": r[3],
                "unrealized_pnl": r[4],
                "realized_pnl": r[5],
            }
            for r in rows
        ]


class TradeRepo:
    """CRUD for trades table. Uses INSERT OR IGNORE for dedup by trade_id."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self,
        trade_id: str,
        env: str,
        timestamp: int,
        instrument_name: str,
        direction: str,
        price: float,
        amount: float,
        fee: float = 0.0,
        fee_currency: str = "",
        pnl: float | None = None,
        order_id: str = "",
        label: str | None = None,
    ) -> None:
        await self._db.connection.execute(
            """INSERT OR IGNORE INTO trades
               (trade_id, env, timestamp, instrument_name, direction, price, amount,
                fee, fee_currency, pnl, order_id, label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, env, timestamp, instrument_name, direction, price, amount,
             fee, fee_currency, pnl, order_id, label),
        )
        await self._db.connection.commit()

    async def get_trades(
        self,
        env: str,
        instrument_name: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM trades WHERE env = ?"
        params: list[Any] = [env]

        if instrument_name:
            query += " AND instrument_name = ?"
            params.append(instrument_name)
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        if until is not None:
            query += " AND timestamp <= ?"
            params.append(until)

        query += " ORDER BY timestamp ASC"
        cursor = await self._db.connection.execute(query, params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, r)) for r in rows]


class OrderRepo:
    """CRUD for orders table. Uses INSERT OR REPLACE to update state."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self,
        order_id: str,
        env: str,
        timestamp: int,
        instrument_name: str,
        direction: str,
        order_type: str,
        price: float | None,
        amount: float,
        filled_amount: float = 0.0,
        order_state: str = "open",
        label: str | None = None,
    ) -> None:
        await self._db.connection.execute(
            """INSERT OR REPLACE INTO orders
               (order_id, env, timestamp, instrument_name, direction, order_type,
                price, amount, filled_amount, order_state, label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, env, timestamp, instrument_name, direction, order_type,
             price, amount, filled_amount, order_state, label),
        )
        await self._db.connection.commit()

    async def get_orders(
        self,
        env: str,
        instrument_name: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM orders WHERE env = ?"
        params: list[Any] = [env]

        if instrument_name:
            query += " AND instrument_name = ?"
            params.append(instrument_name)
        if state:
            query += " AND order_state = ?"
            params.append(state)

        query += " ORDER BY timestamp DESC"
        cursor = await self._db.connection.execute(query, params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, r)) for r in rows]


class PositionHistoryRepo:
    """CRUD for positions_history table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_snapshot(
        self,
        timestamp: int,
        env: str,
        positions: list[dict[str, Any]],
    ) -> None:
        for p in positions:
            await self._db.connection.execute(
                """INSERT INTO positions_history
                   (timestamp, env, instrument_name, direction, size, average_price,
                    mark_price, pnl, delta, gamma, theta, vega)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp, env,
                    p.get("instrument_name", ""),
                    p.get("direction", ""),
                    p.get("size", 0),
                    p.get("average_price", 0),
                    p.get("mark_price", 0),
                    p.get("floating_profit_loss", 0),
                    p.get("delta"),
                    p.get("gamma"),
                    p.get("theta"),
                    p.get("vega"),
                ),
            )
        await self._db.connection.commit()

    async def get_snapshots(
        self, env: str, since: int, until: int
    ) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            """SELECT * FROM positions_history
               WHERE env = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (env, since, until),
        )
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, r)) for r in rows]


class MarketTickerRepo:
    """CRUD for market_tickers table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_ticker(
        self,
        timestamp: int,
        env: str,
        instrument_name: str,
        mark_price: float | None = None,
        index_price: float | None = None,
        last_price: float | None = None,
        best_bid: float | None = None,
        best_ask: float | None = None,
        implied_volatility: float | None = None,
        funding_rate: float | None = None,
        volume_24h: float | None = None,
    ) -> None:
        await self._db.connection.execute(
            """INSERT INTO market_tickers
               (timestamp, env, instrument_name, mark_price, index_price, last_price,
                best_bid, best_ask, implied_volatility, funding_rate, volume_24h)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, env, instrument_name, mark_price, index_price, last_price,
             best_bid, best_ask, implied_volatility, funding_rate, volume_24h),
        )
        await self._db.connection.commit()

    async def get_tickers(
        self,
        env: str,
        instrument_name: str,
        since: int,
        until: int,
    ) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            """SELECT timestamp, instrument_name, mark_price, index_price, last_price,
                      best_bid, best_ask, implied_volatility, funding_rate, volume_24h
               FROM market_tickers
               WHERE env = ? AND instrument_name = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (env, instrument_name, since, until),
        )
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, r)) for r in rows]


class MarketCandleRepo:
    """CRUD for market_candles table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_candle(
        self,
        timestamp: int,
        env: str,
        instrument_name: str,
        resolution: str,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0,
    ) -> None:
        await self._db.connection.execute(
            """INSERT OR IGNORE INTO market_candles
               (timestamp, env, instrument_name, resolution, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, env, instrument_name, resolution, open, high, low, close, volume),
        )
        await self._db.connection.commit()

    async def save_candles_batch(self, candles: list[tuple]) -> None:
        """Batch insert. Each tuple: (timestamp, env, instrument, resolution, o, h, l, c, v)."""
        await self._db.connection.executemany(
            """INSERT OR IGNORE INTO market_candles
               (timestamp, env, instrument_name, resolution, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            candles,
        )
        await self._db.connection.commit()

    async def get_candles(
        self,
        env: str,
        instrument_name: str,
        resolution: str,
        since: int,
        until: int,
    ) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            """SELECT timestamp, instrument_name, resolution, open, high, low, close, volume
               FROM market_candles
               WHERE env = ? AND instrument_name = ? AND resolution = ?
                 AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (env, instrument_name, resolution, since, until),
        )
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, r)) for r in rows]
