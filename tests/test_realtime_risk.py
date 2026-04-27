"""Tests for realtime data recording and risk management."""

import os
import tempfile

import pytest
import pytest_asyncio

from deribit_trading.persistence import Database
from deribit_trading.persistence.repositories import MarketTickerRepo, MarketCandleRepo
from deribit_trading.services.risk_manager import RiskConfig, RiskLimitError, RiskManager
from deribit_trading.services.market_data_recorder import CandleWindow


# ── Fixtures ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    d = Database(db_path)
    await d.open()
    yield d
    await d.close()
    os.unlink(db_path)


# ── Schema migration ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schema_v2_creates_tables(db: Database):
    """Schema v2 should create market_tickers and market_candles tables."""
    cursor = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('market_tickers', 'market_candles')"
    )
    tables = [r[0] for r in await cursor.fetchall()]
    assert "market_tickers" in tables
    assert "market_candles" in tables


# ── MarketTickerRepo ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticker_save_and_query(db: Database):
    repo = MarketTickerRepo(db)
    await repo.save_ticker(
        timestamp=1000, env="testnet", instrument_name="BTC-PERPETUAL",
        mark_price=94000, last_price=93990, best_bid=93980, best_ask=94010,
    )
    await repo.save_ticker(
        timestamp=2000, env="testnet", instrument_name="BTC-PERPETUAL",
        mark_price=94100, last_price=94090, best_bid=94080, best_ask=94110,
    )

    rows = await repo.get_tickers("testnet", "BTC-PERPETUAL", 0, 3000)
    assert len(rows) == 2
    assert rows[0]["mark_price"] == 94000
    assert rows[1]["mark_price"] == 94100


@pytest.mark.asyncio
async def test_ticker_env_isolation(db: Database):
    repo = MarketTickerRepo(db)
    await repo.save_ticker(
        timestamp=1000, env="testnet", instrument_name="BTC-PERPETUAL", mark_price=100,
    )
    await repo.save_ticker(
        timestamp=1000, env="production", instrument_name="BTC-PERPETUAL", mark_price=200,
    )
    testnet = await repo.get_tickers("testnet", "BTC-PERPETUAL", 0, 9999)
    assert len(testnet) == 1
    assert testnet[0]["mark_price"] == 100


# ── MarketCandleRepo ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_candle_save_and_query(db: Database):
    repo = MarketCandleRepo(db)
    await repo.save_candle(
        timestamp=60000, env="testnet", instrument_name="BTC-PERPETUAL",
        resolution="1m", open=94000, high=94100, low=93900, close=94050, volume=1000,
    )
    rows = await repo.get_candles("testnet", "BTC-PERPETUAL", "1m", 0, 99999)
    assert len(rows) == 1
    assert rows[0]["open"] == 94000
    assert rows[0]["close"] == 94050


@pytest.mark.asyncio
async def test_candle_dedup(db: Database):
    repo = MarketCandleRepo(db)
    await repo.save_candle(
        timestamp=60000, env="testnet", instrument_name="BTC-PERPETUAL",
        resolution="1m", open=100, high=110, low=90, close=105, volume=500,
    )
    # Same PK → should be ignored
    await repo.save_candle(
        timestamp=60000, env="testnet", instrument_name="BTC-PERPETUAL",
        resolution="1m", open=200, high=220, low=180, close=210, volume=999,
    )
    rows = await repo.get_candles("testnet", "BTC-PERPETUAL", "1m", 0, 99999)
    assert len(rows) == 1
    assert rows[0]["open"] == 100  # first insert wins


@pytest.mark.asyncio
async def test_candle_batch_insert(db: Database):
    repo = MarketCandleRepo(db)
    candles = [
        (60000, "testnet", "BTC-PERPETUAL", "1m", 100, 110, 90, 105, 500),
        (120000, "testnet", "BTC-PERPETUAL", "1m", 105, 115, 95, 110, 600),
        (180000, "testnet", "BTC-PERPETUAL", "1m", 110, 120, 100, 115, 700),
    ]
    await repo.save_candles_batch(candles)
    rows = await repo.get_candles("testnet", "BTC-PERPETUAL", "1m", 0, 999999)
    assert len(rows) == 3


# ── CandleWindow (OHLCV aggregation) ───────────────────────────────

def test_candle_window_aggregation():
    w = CandleWindow(instrument="BTC-PERPETUAL", resolution_ms=60000)

    w.update(100, 10, 0)      # first tick
    w.update(110, 20, 10000)  # high
    w.update(90, 15, 20000)   # low
    w.update(105, 25, 50000)  # close

    assert w.open == 100
    assert w.high == 110
    assert w.low == 90
    assert w.close == 105
    assert w.count == 4


def test_candle_window_detects_completion():
    w = CandleWindow(instrument="BTC-PERPETUAL", resolution_ms=60000)
    w.update(100, 10, 0)
    assert not w.is_window_complete(30000)  # 30s in, same window
    assert w.is_window_complete(60000)      # new window


def test_candle_window_flush():
    w = CandleWindow(instrument="BTC-PERPETUAL", resolution_ms=60000)
    w.update(100, 10, 5000)
    w.update(110, 20, 30000)
    ts, o, h, l, c, v = w.flush()
    assert ts == 0  # window_start snapped to 0
    assert o == 100
    assert h == 110
    assert w.count == 0  # reset after flush


# ── RiskManager ─────────────────────────────────────────────────────

def test_risk_check_passes():
    rm = RiskManager(RiskConfig(max_order_size_usd=10000))
    rm.check("BTC-PERPETUAL", "buy", 0.1, 94000)  # 0.1 * 94000 = $9400 < $10000


def test_risk_check_order_size_limit():
    rm = RiskManager(RiskConfig(max_order_size_usd=1000))
    with pytest.raises(RiskLimitError, match="max_order_size"):
        rm.check("BTC-PERPETUAL", "buy", 0.1, 94000)  # $9400 > $1000


def test_risk_daily_loss_pause():
    rm = RiskManager(RiskConfig(daily_loss_limit_usd=100))
    assert not rm.trading_paused

    rm.update_pnl(-50)
    assert not rm.trading_paused

    rm.update_pnl(-60)  # total -110 > -100 limit
    assert rm.trading_paused


def test_risk_daily_loss_blocks_trading():
    rm = RiskManager(RiskConfig(daily_loss_limit_usd=100))
    rm.update_pnl(-150)
    assert rm.trading_paused

    with pytest.raises(RiskLimitError, match="trading_paused"):
        rm.check("BTC-PERPETUAL", "buy", 0.1, 94000)


def test_risk_resume():
    rm = RiskManager(RiskConfig(daily_loss_limit_usd=100))
    rm.update_pnl(-150)
    assert rm.trading_paused

    rm.resume_trading()
    assert not rm.trading_paused
    rm.check("BTC-PERPETUAL", "buy", 0.01, 94000)  # should not raise


def test_risk_status():
    rm = RiskManager(RiskConfig(daily_loss_limit_usd=5000))
    rm.update_pnl(-200)
    status = rm.get_risk_status()
    assert status["daily_pnl"] == -200
    assert status["trading_paused"] is False
    assert status["config"]["daily_loss_limit_usd"] == 5000


def test_risk_config_update():
    rm = RiskManager()
    rm.update_config(max_order_size_usd=50000, daily_loss_limit_usd=2000)
    assert rm.config.max_order_size_usd == 50000
    assert rm.config.daily_loss_limit_usd == 2000


# ── API integration ─────────────────────────────────────────────────

needs_api = pytest.mark.skipif(
    not os.getenv("DERIBIT_CLIENT_ID"),
    reason="DERIBIT_CLIENT_ID not set",
)

TESTNET_URL = "wss://test.deribit.com/ws/api/v2"


@needs_api
@pytest.mark.asyncio
async def test_order_monitor_auto_subscribe():
    """Verify OrderMonitor can subscribe and the connection works."""
    from deribit_trading.client import DeribitClient
    from deribit_trading.services.order_monitor import OrderMonitor

    client = DeribitClient(TESTNET_URL)
    await client.connect()
    await client.authenticate(
        os.getenv("DERIBIT_CLIENT_ID", ""),
        os.getenv("DERIBIT_CLIENT_SECRET", ""),
    )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path)
    await db.open()

    try:
        monitor = OrderMonitor(client, db, env="testnet")
        # This should not raise
        await monitor.subscribe_currency("any")
    finally:
        await client.disconnect()
        await db.close()
        os.unlink(db_path)
