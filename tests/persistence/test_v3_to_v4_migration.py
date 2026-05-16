"""Tests for the v3 → v4 schema migration.

We build a v3-shaped SQLite database manually, then open it via Database
(which triggers _migrate_v3_to_v4) and assert:
  - accounts + active_account tables exist
  - per-account history tables have account_id (not env)
  - existing row data preserved
  - market_tickers / market_candles keep env
  - backfill_history_account_ids rewrites account_id values
"""

import os
import sqlite3
import tempfile

import pytest
import pytest_asyncio

from deribit_trading.persistence import Database


def _create_v3_db(path: str) -> None:
    """Build a v3-shaped database with some sample rows."""
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (3);

            CREATE TABLE equity_snapshots (
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
            CREATE TABLE trades (
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
            CREATE TABLE orders (
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
            CREATE TABLE positions_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                env TEXT NOT NULL,
                instrument_name TEXT NOT NULL,
                direction TEXT NOT NULL,
                size REAL NOT NULL,
                average_price REAL NOT NULL,
                mark_price REAL NOT NULL,
                pnl REAL NOT NULL DEFAULT 0,
                delta REAL, gamma REAL, theta REAL, vega REAL
            );
            CREATE TABLE market_tickers (
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
            );
            CREATE TABLE market_candles (
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
            );
            CREATE TABLE agent_write_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                decision TEXT NOT NULL,
                decision_reason TEXT,
                env TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            -- sample data
            INSERT INTO equity_snapshots (timestamp, env, currency, equity, balance)
                VALUES (1, 'production', 'BTC', 1.0, 1.0),
                       (2, 'testnet', 'ETH', 5.0, 5.0);
            INSERT INTO trades (trade_id, env, timestamp, instrument_name, direction, price, amount)
                VALUES ('t1', 'production', 1, 'BTC-PERPETUAL', 'buy', 80000, 10);
            INSERT INTO orders (order_id, env, timestamp, instrument_name, direction, order_type, amount, order_state)
                VALUES ('o1', 'testnet', 1, 'BTC-PERPETUAL', 'buy', 'market', 10, 'filled');
            INSERT INTO positions_history (timestamp, env, instrument_name, direction, size, average_price, mark_price)
                VALUES (1, 'production', 'BTC-PERPETUAL', 'buy', 100, 80000, 80100);
            INSERT INTO agent_write_audit
                (tool_call_id, tool_name, args_json, summary, decision, env, created_at)
                VALUES ('tc1', 'place_order', '{}', 's', 'confirmed', 'testnet', 1);
            INSERT INTO market_tickers (timestamp, env, instrument_name)
                VALUES (1, 'production', 'BTC-PERPETUAL');
            INSERT INTO market_candles (timestamp, env, instrument_name, resolution, open, high, low, close)
                VALUES (1, 'production', 'BTC-PERPETUAL', '1m', 1, 1, 1, 1);
        """)


@pytest_asyncio.fixture
async def migrated_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    _create_v3_db(tmp.name)
    database = Database(tmp.name)
    await database.open()  # triggers v3→v4
    yield database
    await database.close()
    os.unlink(tmp.name)


@pytest.mark.asyncio
async def test_version_bumped_to_4(migrated_db):
    cursor = await migrated_db.connection.execute(
        "SELECT version FROM schema_version LIMIT 1"
    )
    row = await cursor.fetchone()
    assert row[0] == 4


@pytest.mark.asyncio
async def test_accounts_and_active_tables_exist(migrated_db):
    for name in ("accounts", "active_account"):
        cursor = await migrated_db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        assert (await cursor.fetchone()) is not None, f"{name} missing"


@pytest.mark.asyncio
async def test_per_account_tables_renamed(migrated_db):
    """env column → account_id on the 5 per-account history tables."""
    for table in (
        "equity_snapshots",
        "trades",
        "orders",
        "positions_history",
        "agent_write_audit",
    ):
        cursor = await migrated_db.connection.execute(f"PRAGMA table_info({table})")
        cols = [c[1] for c in await cursor.fetchall()]
        assert "account_id" in cols, f"{table} missing account_id"
        assert "env" not in cols, f"{table} still has env"


@pytest.mark.asyncio
async def test_market_data_tables_keep_env(migrated_db):
    """market_tickers / market_candles must retain env column."""
    for table in ("market_tickers", "market_candles"):
        cursor = await migrated_db.connection.execute(f"PRAGMA table_info({table})")
        cols = [c[1] for c in await cursor.fetchall()]
        assert "env" in cols, f"{table} should keep env"
        assert "account_id" not in cols, f"{table} should NOT have account_id"


@pytest.mark.asyncio
async def test_data_preserved_with_account_id_holding_old_env(migrated_db):
    """Pre-migration rows keep their data; the renamed column still holds the
    legacy env string until backfill rewrites it."""
    cursor = await migrated_db.connection.execute(
        "SELECT account_id, currency, equity FROM equity_snapshots ORDER BY timestamp"
    )
    rows = await cursor.fetchall()
    assert rows == [("production", "BTC", 1.0), ("testnet", "ETH", 5.0)]


@pytest.mark.asyncio
async def test_backfill_rewrites_account_id(migrated_db):
    env_to_uuid = {"production": "uuid-prod", "testnet": "uuid-test"}
    total = await migrated_db.backfill_history_account_ids(env_to_uuid)
    # 2 equity + 1 trade + 1 order + 1 position + 1 audit = 6 rows
    assert total == 6
    cursor = await migrated_db.connection.execute(
        "SELECT DISTINCT account_id FROM equity_snapshots"
    )
    ids = sorted(r[0] for r in await cursor.fetchall())
    assert ids == ["uuid-prod", "uuid-test"]


@pytest.mark.asyncio
async def test_backfill_idempotent(migrated_db):
    """Second run is a no-op (no rows match the old env strings anymore)."""
    env_to_uuid = {"production": "uuid-prod", "testnet": "uuid-test"}
    first = await migrated_db.backfill_history_account_ids(env_to_uuid)
    second = await migrated_db.backfill_history_account_ids(env_to_uuid)
    assert first > 0 and second == 0
