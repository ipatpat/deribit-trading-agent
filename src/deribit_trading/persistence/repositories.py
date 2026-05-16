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
        account_id: str,
        currency: str,
        equity: float,
        balance: float,
        margin_balance: float = 0.0,
        unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0,
    ) -> None:
        await self._db.connection.execute(
            """INSERT INTO equity_snapshots
               (timestamp, account_id, currency, equity, balance, margin_balance, unrealized_pnl, realized_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, account_id, currency, equity, balance, margin_balance, unrealized_pnl, realized_pnl),
        )
        await self._db.connection.commit()

    async def get_range(
        self,
        account_id: str,
        currency: str,
        since: int,
        until: int,
    ) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            """SELECT timestamp, equity, balance, margin_balance, unrealized_pnl, realized_pnl
               FROM equity_snapshots
               WHERE account_id = ? AND currency = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (account_id, currency, since, until),
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
        account_id: str,
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
               (trade_id, account_id, timestamp, instrument_name, direction, price, amount,
                fee, fee_currency, pnl, order_id, label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, account_id, timestamp, instrument_name, direction, price, amount,
             fee, fee_currency, pnl, order_id, label),
        )
        await self._db.connection.commit()

    async def get_trades(
        self,
        account_id: str,
        instrument_name: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM trades WHERE account_id = ?"
        params: list[Any] = [account_id]

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
        account_id: str,
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
               (order_id, account_id, timestamp, instrument_name, direction, order_type,
                price, amount, filled_amount, order_state, label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, account_id, timestamp, instrument_name, direction, order_type,
             price, amount, filled_amount, order_state, label),
        )
        await self._db.connection.commit()

    async def get_orders(
        self,
        account_id: str,
        instrument_name: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM orders WHERE account_id = ?"
        params: list[Any] = [account_id]

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
        account_id: str,
        positions: list[dict[str, Any]],
    ) -> None:
        for p in positions:
            await self._db.connection.execute(
                """INSERT INTO positions_history
                   (timestamp, account_id, instrument_name, direction, size, average_price,
                    mark_price, pnl, delta, gamma, theta, vega)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp, account_id,
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
        self, account_id: str, since: int, until: int
    ) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            """SELECT * FROM positions_history
               WHERE account_id = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (account_id, since, until),
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


class WriteAuditRepo:
    """CRUD for agent_write_audit table.

    Records every user decision on a write-tool call (confirmed / declined /
    timeout) for compliance + dispute resolution. Each row is a complete
    audit trail entry for one tool_call_id.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, decision: dict[str, Any]) -> None:
        """Insert one audit row.

        decision must include: tool_call_id, tool_name, args_json, summary,
        decision (∈ {'confirmed', 'declined', 'timeout'}), account_id.
        Optional: decision_reason. `created_at` is auto-filled with current
        ms epoch.
        """
        import time

        await self._db.connection.execute(
            """INSERT INTO agent_write_audit
               (tool_call_id, tool_name, args_json, summary,
                decision, decision_reason, account_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision["tool_call_id"],
                decision["tool_name"],
                decision["args_json"],
                decision["summary"],
                decision["decision"],
                decision.get("decision_reason"),
                decision["account_id"],
                int(time.time() * 1000),
            ),
        )
        await self._db.connection.commit()

    async def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent audit entries, newest first."""
        cursor = await self._db.connection.execute(
            """SELECT tool_call_id, tool_name, args_json, summary,
                      decision, decision_reason, account_id, created_at
               FROM agent_write_audit
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, r)) for r in rows]


class AccountRepo:
    """CRUD for accounts + active_account tables.

    Encryption is the caller's concern: pass in already-Fernet-encrypted
    secret BLOBs to create()/update(); get() returns BLOBs as-is. The
    rationale is that this repo lives in the public data DB while the
    Fernet instance is owned by KeyStore in a different module.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_all(self) -> list[dict[str, Any]]:
        """Return all accounts including the encrypted secret BLOB.

        The REST endpoint decrypts to expose only the last-4 tail to the
        frontend — callers that don't need the secret can ignore the field.
        Ordered by last_used_at DESC NULLS LAST, then created_at DESC.
        """
        cursor = await self._db.connection.execute(
            """SELECT id, alias, endpoint, client_id, client_secret,
                      created_at, last_used_at
               FROM accounts
               ORDER BY COALESCE(last_used_at, 0) DESC, created_at DESC"""
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "alias": r[1],
                "endpoint": r[2],
                "client_id": r[3],
                "client_secret": r[4],
                "created_at": r[5],
                "last_used_at": r[6],
            }
            for r in rows
        ]

    async def get(self, account_id: str) -> dict[str, Any] | None:
        """Return one account including the encrypted secret BLOB."""
        cursor = await self._db.connection.execute(
            """SELECT id, alias, endpoint, client_id, client_secret,
                      created_at, last_used_at
               FROM accounts WHERE id = ?""",
            (account_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "alias": row[1],
            "endpoint": row[2],
            "client_id": row[3],
            "client_secret": row[4],  # BLOB, encrypted
            "created_at": row[5],
            "last_used_at": row[6],
        }

    async def get_by_alias(self, alias: str) -> dict[str, Any] | None:
        cursor = await self._db.connection.execute(
            "SELECT id FROM accounts WHERE alias = ?", (alias,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return await self.get(row[0])

    async def create(
        self,
        account_id: str,
        alias: str,
        endpoint: str,
        client_id: str,
        client_secret_encrypted: bytes,
        created_at: int,
    ) -> None:
        await self._db.connection.execute(
            """INSERT INTO accounts
               (id, alias, endpoint, client_id, client_secret, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (account_id, alias, endpoint, client_id, client_secret_encrypted, created_at),
        )
        await self._db.connection.commit()

    async def update(
        self,
        account_id: str,
        alias: str | None = None,
        client_secret_encrypted: bytes | None = None,
    ) -> bool:
        """Update mutable fields. Returns True if a row was updated."""
        sets: list[str] = []
        params: list[Any] = []
        if alias is not None:
            sets.append("alias = ?")
            params.append(alias)
        if client_secret_encrypted is not None:
            sets.append("client_secret = ?")
            params.append(client_secret_encrypted)
        if not sets:
            return False
        params.append(account_id)
        cursor = await self._db.connection.execute(
            f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        await self._db.connection.commit()
        return cursor.rowcount > 0

    async def delete(self, account_id: str) -> bool:
        """Delete an account. Caller must ensure it's not active."""
        cursor = await self._db.connection.execute(
            "DELETE FROM accounts WHERE id = ?", (account_id,)
        )
        await self._db.connection.commit()
        return cursor.rowcount > 0

    async def touch_last_used(self, account_id: str, when_ms: int) -> None:
        await self._db.connection.execute(
            "UPDATE accounts SET last_used_at = ? WHERE id = ?",
            (when_ms, account_id),
        )
        await self._db.connection.commit()

    # ── Active account (singleton) ─────────────────────────────────────────

    async def get_active_id(self) -> str | None:
        cursor = await self._db.connection.execute(
            "SELECT account_id FROM active_account WHERE id = 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_active(self, account_id: str) -> None:
        """Set the active account. Replaces any previous selection."""
        await self._db.connection.execute(
            """INSERT INTO active_account (id, account_id) VALUES (1, ?)
               ON CONFLICT(id) DO UPDATE SET account_id = excluded.account_id""",
            (account_id,),
        )
        await self._db.connection.commit()

    async def clear_active(self) -> None:
        await self._db.connection.execute("DELETE FROM active_account WHERE id = 1")
        await self._db.connection.commit()
