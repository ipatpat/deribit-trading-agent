"""Integration tests against Deribit testnet.

Run with: pytest tests/test_integration.py -v

Tests are split into:
  - Local tests (persistence): always run
  - API tests (Deribit testnet): require DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET
"""

import os
import tempfile

import pytest
import pytest_asyncio

from deribit_trading.client import DeribitClient
from deribit_trading.config import EnvManager, Environment
from deribit_trading.persistence import Database, EquitySnapshotRepo
from deribit_trading.persistence.queries import auto_bucket_ms, get_equity_bucketed
from deribit_trading.services import MarketDataService, PortfolioService, TradingService

TESTNET_URL = "wss://test.deribit.com/ws/api/v2"

needs_api = pytest.mark.skipif(
    not os.getenv("DERIBIT_CLIENT_ID"),
    reason="DERIBIT_CLIENT_ID not set",
)


# ── Local fixtures (no network) ────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    d = Database(db_path)
    await d.open()
    yield d
    await d.close()
    os.unlink(db_path)


# ── API fixtures ────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    c = DeribitClient(TESTNET_URL)
    await c.connect()
    client_id = os.getenv("DERIBIT_CLIENT_ID", "")
    client_secret = os.getenv("DERIBIT_CLIENT_SECRET", "")
    if client_id and client_secret:
        await c.authenticate(client_id, client_secret)
    yield c
    await c.disconnect()


# ── Local tests (always run) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_equity_snapshot_crud(db: Database):
    repo = EquitySnapshotRepo(db)
    await repo.save(
        timestamp=1000000, account_id="testnet", currency="BTC",
        equity=1.5, balance=1.5, margin_balance=0.1,
        unrealized_pnl=0.0, realized_pnl=0.0,
    )
    await repo.save(
        timestamp=2000000, account_id="testnet", currency="BTC",
        equity=1.6, balance=1.5, margin_balance=0.1,
        unrealized_pnl=0.1, realized_pnl=0.0,
    )
    rows = await repo.get_range("testnet", "BTC", 0, 3000000)
    assert len(rows) == 2
    assert rows[0]["equity"] == 1.5
    assert rows[1]["equity"] == 1.6


@pytest.mark.asyncio
async def test_equity_env_isolation(db: Database):
    """Production and testnet data should be isolated."""
    repo = EquitySnapshotRepo(db)
    await repo.save(
        timestamp=1000, account_id="testnet", currency="BTC",
        equity=1.0, balance=1.0,
    )
    await repo.save(
        timestamp=1000, account_id="production", currency="BTC",
        equity=99.0, balance=99.0,
    )
    testnet_rows = await repo.get_range("testnet", "BTC", 0, 9999)
    prod_rows = await repo.get_range("production", "BTC", 0, 9999)
    assert len(testnet_rows) == 1
    assert testnet_rows[0]["equity"] == 1.0
    assert len(prod_rows) == 1
    assert prod_rows[0]["equity"] == 99.0


@pytest.mark.asyncio
async def test_bucketed_query(db: Database):
    """SQL bucketed aggregation should produce AVG/MIN/MAX per bucket."""
    repo = EquitySnapshotRepo(db)
    # Insert 3 points in the same 1-hour bucket
    for i, equity in enumerate([100.0, 90.0, 110.0]):
        await repo.save(
            timestamp=1000 + i * 1000, account_id="testnet", currency="BTC",
            equity=equity, balance=100.0,
        )

    result = await get_equity_bucketed(
        db, "testnet", "BTC", since=0, until=999999,
        bucket_ms=3_600_000,  # 1 hour bucket
    )
    assert len(result) == 1
    bucket = result[0]
    assert bucket["min_equity"] == 90.0
    assert bucket["max_equity"] == 110.0
    assert abs(bucket["avg_equity"] - 100.0) < 0.01
    assert bucket["point_count"] == 3


@pytest.mark.asyncio
async def test_auto_bucket_ms():
    """auto_bucket_ms should return a reasonable interval."""
    one_hour = 3_600_000
    one_day = 86_400_000

    # 1 day span → should pick a small bucket
    result = auto_bucket_ms(0, one_day, max_points=1000)
    assert result <= one_day

    # 30 day span → should pick a larger bucket
    result = auto_bucket_ms(0, 30 * one_day, max_points=1000)
    assert result >= one_hour


@pytest.mark.asyncio
async def test_env_manager():
    mgr = EnvManager(initial_env=Environment.TESTNET)
    assert mgr.current_env == Environment.TESTNET
    assert not mgr.is_production()
    assert mgr.ws_url == "wss://test.deribit.com/ws/api/v2"

    # Should allow trading on testnet regardless
    mgr.check_trading_allowed()  # no exception

    # Switch to production — EnvManager defaults the production endpoint to
    # tibired (matches the runtime default).
    mgr.set_env(Environment.PRODUCTION)
    assert mgr.is_production()
    assert mgr.ws_url == "wss://www.tibired.com/ws/api/v2"

    # Should block trading when allow_live_trading=False
    with pytest.raises(PermissionError):
        mgr.check_trading_allowed()

    # Enable live trading
    mgr.set_allow_live_trading(True)
    mgr.check_trading_allowed()  # no exception


@pytest.mark.asyncio
async def test_key_store(db: Database):
    """KeyStore should encrypt/decrypt and select by scope."""
    from deribit_trading.config import KeyStore
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        keys_path = f.name

    try:
        store = KeyStore(keys_path, master_password="test-password-123")

        # Add keys
        store.add_key(
            env=Environment.TESTNET, name="read-only",
            client_id="id1", client_secret="secret1",
            scopes="account:read,trade:read",
        )
        store.add_key(
            env=Environment.TESTNET, name="trading",
            client_id="id2", client_secret="secret2",
            scopes="account:read,trade:read,trade:read_write",
        )

        # List keys (no secrets exposed)
        keys = store.list_keys(Environment.TESTNET)
        assert len(keys) == 2
        assert all(not hasattr(k, "client_secret") for k in keys)

        # Get specific key with decrypted secret
        key = store.get_key(Environment.TESTNET, "read-only")
        assert key is not None
        assert key.client_secret == "secret1"

        # Least privilege selection
        read_key = store.get_key_for_scope(Environment.TESTNET, "account:read")
        assert read_key.name == "read-only"  # fewer scopes = preferred

        # Remove key
        assert store.remove_key(Environment.TESTNET, "read-only")
        assert len(store.list_keys(Environment.TESTNET)) == 1
    finally:
        os.unlink(keys_path)


# ── API tests (require credentials) ────────────────────────────────

@needs_api
@pytest.mark.asyncio
async def test_connect_and_auth(client: DeribitClient):
    assert client.is_connected
    assert client.is_authenticated


@needs_api
@pytest.mark.asyncio
async def test_get_ticker(client: DeribitClient):
    ticker = await client.get_ticker("BTC-PERPETUAL")
    assert ticker.instrument_name == "BTC-PERPETUAL"
    assert ticker.mark_price > 0


@needs_api
@pytest.mark.asyncio
async def test_get_instruments(client: DeribitClient):
    instruments = await client.get_instruments("BTC", kind="future")
    assert len(instruments) > 0
    perp = [i for i in instruments if "PERPETUAL" in i.instrument_name]
    assert len(perp) > 0


@needs_api
@pytest.mark.asyncio
async def test_get_account_summary(client: DeribitClient):
    summary = await client.get_account_summary("BTC")
    assert summary.currency == "BTC"
    assert summary.equity >= 0


@needs_api
@pytest.mark.asyncio
async def test_get_positions(client: DeribitClient):
    positions = await client.get_positions("BTC")
    assert isinstance(positions, list)


@needs_api
@pytest.mark.asyncio
async def test_place_and_cancel_order(client: DeribitClient):
    """Place a limit order far from market, then cancel it."""
    ticker = await client.get_ticker("BTC-PERPETUAL")
    far_price = round(ticker.mark_price * 0.5 / 5) * 5
    if far_price < 5:
        far_price = 5

    order = await client.buy(
        instrument_name="BTC-PERPETUAL",
        amount=10,
        order_type="limit",
        price=far_price,
        label="test_order",
    )
    assert order.order_id
    assert order.order_state == "open"

    cancelled = await client.cancel(order.order_id)
    assert cancelled.order_state == "cancelled"


@needs_api
@pytest.mark.asyncio
async def test_market_data_service(client: DeribitClient):
    svc = MarketDataService(client)
    ticker = await svc.get_ticker("BTC-PERPETUAL")
    assert ticker.mark_price > 0

    instruments = await svc.get_instruments("BTC")
    assert len(instruments) > 0
