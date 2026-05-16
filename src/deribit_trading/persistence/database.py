"""SQLite database management with auto-migration."""

import logging
import re
import shutil
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 4

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

    @property
    def path(self) -> str:
        return self._db_path

    async def open(self) -> None:
        """Open database and ensure schema is up to date.

        If a migration to a newer schema version is needed, a timestamped
        backup of the DB file is created at `<db_path>.bak.<unix_seconds>`
        BEFORE running the migration. Restore from that file if anything
        goes wrong.
        """
        # Best-effort backup check BEFORE opening (so we don't backup an
        # exclusive-locked connection state).
        await self._maybe_backup()

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

    async def _maybe_backup(self) -> None:
        """If the DB file exists and reports a schema version < current, copy
        the file to <path>.bak.<timestamp> before any migration runs."""
        src = Path(self._db_path)
        if not src.exists():
            return  # fresh install, nothing to back up

        # Peek at schema_version with a throwaway connection to decide whether
        # backup is warranted.
        try:
            probe = await aiosqlite.connect(self._db_path)
            try:
                cursor = await probe.execute("SELECT version FROM schema_version LIMIT 1")
                row = await cursor.fetchone()
                version = row[0] if row else 0
            except aiosqlite.OperationalError:
                version = 0
            finally:
                await probe.close()
        except Exception:  # noqa: BLE001
            return  # malformed DB; let _migrate handle (or fail loudly)

        if version >= CURRENT_SCHEMA_VERSION:
            return  # already up to date

        ts = int(time.time())
        backup_path = src.with_name(f"{src.name}.bak.{ts}")
        try:
            shutil.copy2(src, backup_path)
            logger.warning(
                "DB migration imminent (v%d → v%d). Backup written: %s",
                version,
                CURRENT_SCHEMA_VERSION,
                backup_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Backup failed before migration: %s", exc)

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
            version = 2

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
            version = 3

        if version < 4:
            await self._migrate_v3_to_v4()
            await self._set_version(4)
            await db.commit()
            logger.info("Database migrated to schema version 4 (multi-account)")
            version = 4

    async def _migrate_v3_to_v4(self) -> None:
        """v3 → v4: multi-account schema.

        Adds `accounts` + `active_account` tables, and renames the `env`
        column on per-account history tables to `account_id`. The data
        backfill from legacy api_keys → default accounts is performed by the
        application bootstrap layer (it requires access to KeyStore for
        decrypted secrets); this migration only does the structural DDL and
        leaves `account_id` columns populated with the old env strings as
        placeholders until backfill runs.

        market_tickers and market_candles retain their `env` column (market
        data is shared across accounts).
        """
        db = self.connection

        # 1. accounts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id            TEXT PRIMARY KEY,
                alias         TEXT NOT NULL UNIQUE,
                endpoint      TEXT NOT NULL,
                client_id     TEXT NOT NULL,
                client_secret BLOB NOT NULL,
                created_at    INTEGER NOT NULL,
                last_used_at  INTEGER
            )
        """)

        # 2. active_account singleton
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                account_id TEXT NOT NULL REFERENCES accounts(id)
            )
        """)

        # 3. Rename env → account_id on per-account history tables.
        # SQLite ≥3.25 supports RENAME COLUMN directly; the version shipped
        # with modern Python is fine, but we use the create-copy-drop-rename
        # pattern for safety + portability.
        per_account_tables = [
            "equity_snapshots",
            "trades",
            "orders",
            "positions_history",
            "agent_write_audit",
        ]
        for table in per_account_tables:
            await self._rename_env_to_account_id(table)

    async def _rename_env_to_account_id(self, table: str) -> None:
        """Rename the `env` column to `account_id` on a single table by
        recreating it. The values are copied verbatim — the bootstrap layer
        is expected to UPDATE them from old env strings to account uuids
        once a env→uuid map is available."""
        db = self.connection

        # Get the existing CREATE TABLE statement.
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        row = await cursor.fetchone()
        if not row:
            logger.warning("Skipping rename: table %s does not exist", table)
            return

        old_sql: str = row[0]
        # Get column list from PRAGMA.
        cursor = await db.execute(f"PRAGMA table_info({table})")
        cols = await cursor.fetchall()
        col_names = [c[1] for c in cols]
        if "env" not in col_names:
            logger.info("Skipping rename on %s: no env column", table)
            return
        if "account_id" in col_names:
            logger.info("Skipping rename on %s: account_id already exists", table)
            return

        # Replace `env` as a standalone identifier with `account_id` —
        # catches both `env TEXT NOT NULL` column defs AND `PRIMARY KEY
        # (..., env)` composite key references. \b word boundaries keep
        # us from accidentally rewriting substrings like "_env" or "env_".
        new_sql = re.sub(r"\benv\b", "account_id", old_sql)
        tmp_table = f"{table}__v4_tmp"
        # Rewrite the table name in the CREATE statement (only the first
        # occurrence, which is the table name itself).
        new_sql_tmp = new_sql.replace(f" {table} ", f" {tmp_table} ", 1).replace(
            f" {table}(", f" {tmp_table}(", 1
        )
        await db.execute(new_sql_tmp)

        # Copy data with column rename
        old_cols = ", ".join(col_names)
        new_cols = ", ".join("account_id" if c == "env" else c for c in col_names)
        await db.execute(
            f"INSERT INTO {tmp_table} ({new_cols}) SELECT {old_cols} FROM {table}"
        )

        # Drop old table + rename tmp into place
        await db.execute(f"DROP TABLE {table}")
        await db.execute(f"ALTER TABLE {tmp_table} RENAME TO {table}")

        # Rebuild known indexes that referenced env. Patterns are hardcoded
        # here because aiosqlite's metadata doesn't carry index DDL portably
        # enough to do this generically.
        if table == "equity_snapshots":
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_equity_ts_env "
                "ON equity_snapshots(account_id, currency, timestamp)"
            )
        elif table == "trades":
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_instrument "
                "ON trades(account_id, instrument_name, timestamp)"
            )
        elif table == "orders":
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_instrument "
                "ON orders(account_id, instrument_name, timestamp)"
            )
        elif table == "positions_history":
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_positions_history_ts "
                "ON positions_history(account_id, timestamp)"
            )
        elif table == "agent_write_audit":
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_created_at "
                "ON agent_write_audit(created_at DESC)"
            )
        logger.info("Renamed env → account_id on table '%s'", table)

    async def _get_version(self) -> int:
        db = self.connection
        try:
            cursor = await db.execute("SELECT version FROM schema_version LIMIT 1")
            row = await cursor.fetchone()
            return row[0] if row else 0
        except aiosqlite.OperationalError:
            return 0

    async def backfill_history_account_ids(
        self, env_to_account_id: dict[str, str]
    ) -> int:
        """Update per-account history tables: rows where account_id still
        contains a legacy env string (`production` / `testnet`) get rewritten
        to the corresponding default account's uuid.

        Called by application bootstrap after KeyStore has imported old
        api_keys into the accounts table and produced this map. Idempotent
        (subsequent runs find no rows matching legacy strings)."""
        if not env_to_account_id:
            return 0
        db = self.connection
        total = 0
        tables = [
            "equity_snapshots",
            "trades",
            "orders",
            "positions_history",
            "agent_write_audit",
        ]
        for env, uuid in env_to_account_id.items():
            for table in tables:
                cursor = await db.execute(
                    f"UPDATE {table} SET account_id = ? WHERE account_id = ?",
                    (uuid, env),
                )
                total += cursor.rowcount
        await db.commit()
        if total:
            logger.info(
                "Backfilled %d history rows: legacy env strings → account uuids",
                total,
            )
        return total

    async def clear_private_data(self, account_id: str) -> int:
        """Delete all per-account private data for the given account_id.
        Returns total rows deleted across the 5 per-account history tables."""
        db = self.connection
        total = 0
        for table in (
            "equity_snapshots",
            "trades",
            "orders",
            "positions_history",
            "agent_write_audit",
        ):
            cursor = await db.execute(
                f"DELETE FROM {table} WHERE account_id = ?", (account_id,)
            )
            total += cursor.rowcount
        await db.commit()
        logger.info(
            "Cleared %d rows of private data for account_id=%s", total, account_id
        )
        return total

    async def _set_version(self, version: int) -> None:
        db = self.connection
        await db.execute("DELETE FROM schema_version")
        await db.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
