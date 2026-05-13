"""SQLite database management with auto-migration."""

import logging

import aiosqlite

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    env TEXT NOT NULL,
    currency TEXT NOT NULL,
    equity REAL NOT NULL,
    balance REAL NOT NULL,
    margin_balance REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_equity_ts_env
    ON equity_snapshots(env, currency, timestamp);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT NOT NULL,
    env TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    instrument_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    fee_currency TEXT NOT NULL DEFAULT '',
    pnl REAL,
    order_id TEXT NOT NULL DEFAULT '',
    label TEXT,
    PRIMARY KEY (trade_id, env)
);

CREATE INDEX IF NOT EXISTS idx_trades_instrument
    ON trades(env, instrument_name, timestamp);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT NOT NULL,
    env TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    instrument_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    order_type TEXT NOT NULL,
    price REAL,
    amount REAL NOT NULL,
    filled_amount REAL NOT NULL DEFAULT 0,
    order_state TEXT NOT NULL,
    label TEXT,
    PRIMARY KEY (order_id, env)
);

CREATE INDEX IF NOT EXISTS idx_orders_instrument
    ON orders(env, instrument_name, timestamp);

CREATE TABLE IF NOT EXISTS positions_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    env TEXT NOT NULL,
    instrument_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    size REAL NOT NULL,
    average_price REAL NOT NULL,
    mark_price REAL NOT NULL,
    pnl REAL NOT NULL DEFAULT 0,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL
);

CREATE INDEX IF NOT EXISTS idx_positions_history_ts
    ON positions_history(env, timestamp);
"""


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not initialized. Call open() first.")
        return self._db

    async def open(self) -> None:
        """Open database and ensure schema is up to date."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._migrate()
        logger.info("Database opened: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _migrate(self) -> None:
        """Run schema migrations."""
        db = self.connection
        version = await self._get_version()

        if version < 1:
            for statement in SCHEMA_V1.strip().split(";"):
                stmt = statement.strip()
                if stmt:
                    await db.execute(stmt)
            await self._set_version(1)
            await db.commit()
            logger.info("Database migrated to schema version 1")
            version = 1

        if version < 2:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS market_tickers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    env TEXT NOT NULL,
                    instrument_name TEXT NOT NULL,
                    mark_price REAL,
                    index_price REAL,
                    last_price REAL,
                    best_bid REAL,
                    best_ask REAL,
                    implied_volatility REAL,
                    funding_rate REAL,
                    volume_24h REAL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tickers_instrument_ts
                    ON market_tickers(env, instrument_name, timestamp)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS market_candles (
                    timestamp INTEGER NOT NULL,
                    env TEXT NOT NULL,
                    instrument_name TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (instrument_name, resolution, timestamp, env)
                )
            """)
            await self._set_version(2)
            await db.commit()
            logger.info("Database migrated to schema version 2")

        if version < 3:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_write_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('confirmed', 'declined', 'timeout')),
                    decision_reason TEXT,
                    env TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_created_at
                    ON agent_write_audit(created_at DESC)
            """)
            await self._set_version(3)
            await db.commit()
            logger.info("Database migrated to schema version 3")

    async def _get_version(self) -> int:
        db = self.connection
        try:
            cursor = await db.execute("SELECT version FROM schema_version LIMIT 1")
            row = await cursor.fetchone()
            return row[0] if row else 0
        except aiosqlite.OperationalError:
            return 0

    async def clear_private_data(self, env: str) -> int:
        """Delete all private account data for the given env. Returns total rows deleted."""
        db = self.connection
        total = 0
        for table in ['equity_snapshots', 'trades', 'orders', 'positions_history']:
            cursor = await db.execute(f"DELETE FROM {table} WHERE env = ?", (env,))
            total += cursor.rowcount
        await db.commit()
        logger.info("Cleared %d rows of private data for env=%s", total, env)
        return total

    async def _set_version(self, version: int) -> None:
        db = self.connection
        await db.execute("DELETE FROM schema_version")
        await db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
