"""Entry point: python -m deribit_trading [mcp|api|all]"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from .client import DeribitClient
from .client.connection import WebSocketConnection
from .config import (
    Account,
    AccountManager,
    EnvManager,
    Environment,
    KeyStore,
    bootstrap_accounts_from_keystore,
    resolve_endpoint,
)
from .mcp_server import run_mcp_server
from .persistence import AccountRepo, Database
from .rest_api import create_rest_app
from .services import MarketDataService, PortfolioService, TradingService
from .services.order_monitor import OrderMonitor
from .services.market_data_recorder import MarketDataRecorder
from .persistence.repositories import MarketCandleRepo
from .services.risk_manager import RiskConfig, RiskManager
# Import algorithm modules to trigger @register_algorithm decorators
import deribit_trading.algorithms.legacy  # noqa: F401  -- registers legacy:* names
import deribit_trading.algorithms.intent_router  # noqa: F401
from .smart_order.engine import SmartOrderEngine

logger = logging.getLogger("deribit_trading")

DEFAULT_DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "deribit.db")
DEFAULT_KEYS_DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "keys.db")


class ServiceContainer:
    """Holds all service instances for dependency injection."""

    def __init__(
        self,
        client: DeribitClient,
        env_manager: EnvManager,
        db: Database,
        market_data: MarketDataService,
        trading: TradingService,
        portfolio: PortfolioService,
        smart_engine: SmartOrderEngine,
        order_monitor: OrderMonitor,
        risk_manager: RiskManager,
        key_store: KeyStore | None = None,
        account_manager: AccountManager | None = None,
        account_repo: AccountRepo | None = None,
    ) -> None:
        self.client = client
        self.env_manager = env_manager
        self.db = db
        self.market_data = market_data
        self.trading = trading
        self.portfolio = portfolio
        self.smart_engine = smart_engine
        self.order_monitor = order_monitor
        self.risk_manager = risk_manager
        self.key_store = key_store
        self.account_manager = account_manager
        self.account_repo = account_repo
        self._start_time = time.time()

    async def deactivate(self) -> None:
        """Tear down the live trading session: clear pending confirmations,
        reset engines, disconnect the WebSocket, and clear the active account
        row. Used when deleting the active account so we don't leave dangling
        state. Leaves the system in the same "no active account" condition
        the boot path handles via the onboarding banner.
        """
        from .agent.loop import clear_pending_confirmations
        clear_pending_confirmations(reason="account_deactivated")
        if self.smart_engine:
            await self.smart_engine.reset()
        if self.portfolio:
            await self.portfolio.reset_cache()
        try:
            await self.client.disconnect()
        except Exception:  # noqa: BLE001
            logger.exception("disconnect during deactivate failed (continuing)")
        if self.account_repo:
            await self.account_repo.clear_active()
        if self.account_manager:
            self.account_manager.set_active_unchecked(None)

    async def activate_account(self, account_id: str) -> dict:
        """Switch the active account: disconnect → reset engines → reconnect.

        Raises:
            ValueError: account_id not found.
            AccountSwitchError: reconnect/auth failed (active stays unchanged).
        """
        if not self.account_repo or not self.account_manager or not self.key_store:
            raise RuntimeError("Account management not initialised in container")

        row = await self.account_repo.get(account_id)
        if not row:
            raise ValueError(f"Account {account_id} not found")

        endpoint_cfg = resolve_endpoint(row["endpoint"])
        secret_plain = self.key_store.decrypt(row["client_secret"])
        new_account = Account(
            id=row["id"],
            alias=row["alias"],
            endpoint=row["endpoint"],
            client_id=row["client_id"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        )

        # Disconnect + reset all client-side state.
        from .agent.loop import clear_pending_confirmations
        clear_pending_confirmations(reason="account_switched")
        await self.smart_engine.reset()
        await self.portfolio.reset_cache()
        await self.client.disconnect()

        # Build new client wired to the target endpoint.
        self.client._url = endpoint_cfg.ws_url
        self.client._connection = WebSocketConnection(endpoint_cfg.ws_url)
        from .client.rpc import JsonRpcManager
        from .client.auth import AuthManager
        self.client._rpc = JsonRpcManager(self.client._connection)
        self.client._auth = AuthManager(self.client._rpc)
        self.client._connection.set_on_reconnect(self.client._on_reconnect)
        self.client._rpc.set_subscription_handler(self.client._on_subscription)
        self.client._subscriptions.clear()
        await self.client.connect()
        await self.client.authenticate(row["client_id"], secret_plain)

        # CRITICAL: flip the active account BEFORE resubscribing. Otherwise
        # initial portfolio snapshots received during start_tracking get
        # written with the previous account_id, corrupting per-account data
        # (the bug we shipped in v4-rc1 had testnet sandbox values appearing
        # under production rows because env_manager was flipped AFTER start_tracking).
        self.account_manager.set_active_unchecked(new_account)
        if hasattr(self.env_manager, "set_env"):
            self.env_manager.set_env(
                Environment.PRODUCTION if endpoint_cfg.is_production
                else Environment.TESTNET
            )
        self.order_monitor._env = (
            "production" if endpoint_cfg.is_production else "testnet"
        )

        # Resubscribe portfolio + order monitor (now tagging writes correctly).
        await self.portfolio.start_tracking("BTC")
        await self.portfolio.start_tracking("ETH")
        await self.order_monitor.subscribe_currency("any")

        # Persist state.
        now_ms = int(time.time() * 1000)
        await self.account_repo.set_active(account_id)
        await self.account_repo.touch_last_used(account_id, now_ms)

        return {
            "id": new_account.id,
            "alias": new_account.alias,
            "endpoint": new_account.endpoint,
            "client_id": new_account.client_id,
            "connected": self.client.is_connected,
            "authenticated": self.client.is_authenticated,
        }

    async def reconnect(self, env_str: str, client_id: str, client_secret: str) -> dict:
        """Hot-switch environment and credentials without restarting."""
        from .config import Environment
        env = Environment(env_str)

        # 1. Stop active systems
        await self.smart_engine.stop()
        self.risk_manager.resume_trading()
        self.risk_manager._daily_pnl = 0.0

        # 2. Disconnect
        await self.client.disconnect()

        # 3. Switch env
        self.env_manager.set_env(env)

        # 4. Reconnect with new URL
        self.client._url = self.env_manager.ws_url
        self.client._connection = WebSocketConnection(self.env_manager.ws_url)
        # Re-wire internals
        from .client.rpc import JsonRpcManager
        from .client.auth import AuthManager
        self.client._rpc = JsonRpcManager(self.client._connection)
        self.client._auth = AuthManager(self.client._rpc)
        self.client._connection.set_on_reconnect(self.client._on_reconnect)
        self.client._rpc.set_subscription_handler(self.client._on_subscription)
        self.client._subscriptions.clear()

        await self.client.connect()
        await self.client.authenticate(client_id, client_secret)

        # 5. Re-subscribe (reset tracking state so start_tracking re-subscribes)
        if hasattr(self.portfolio, '_tracking_currencies'):
            self.portfolio._tracking_currencies.clear()
        await self.portfolio.start_tracking("BTC")
        await self.portfolio.start_tracking("ETH")
        await self.order_monitor.subscribe_currency("any")
        await self.smart_engine.start()

        # Update order_monitor env
        self.order_monitor._env = env_str

        return {
            "env": env_str,
            "connected": self.client.is_connected,
            "authenticated": self.client.is_authenticated,
        }


async def build_container(env: Environment) -> ServiceContainer:
    """Build the service container with all dependencies."""
    env_manager = EnvManager(
        initial_env=env,
        allow_live_trading=os.getenv("ALLOW_LIVE_TRADING", "").lower() == "true",
    )

    # Database
    db_path = os.getenv("DERIBIT_DB_PATH", DEFAULT_DB_PATH)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    await db.open()

    # Keystore + AccountRepo + AccountManager
    keys_db = os.getenv("DERIBIT_KEYS_DB", DEFAULT_KEYS_DB_PATH)
    master_pw = os.getenv("DERIBIT_MASTER_PASSWORD", "deribit-local")
    key_store = KeyStore(keys_db, master_pw)

    # Seed KeyStore from environment variables / .env if keys not already stored
    # Testnet credentials
    test_id = os.getenv("DERIBIT_TEST_CLIENT_ID", os.getenv("deribit_test_client_id", ""))
    test_secret = os.getenv("DERIBIT_TEST_CLIENT_SECRET", os.getenv("deribit_test_client_secret", ""))
    if test_id and test_secret and not key_store.list_keys(Environment.TESTNET):
        key_store.add_key(Environment.TESTNET, "main", test_id, test_secret, "account:read,trade:read_write")
        logger.info("Seeded testnet credentials from env vars")

    # Production credentials
    prod_id = os.getenv("DERIBIT_CLIENT_ID", os.getenv("deribit_client_id", ""))
    prod_secret = os.getenv("DERIBIT_CLIENT_SECRET", os.getenv("deribit_client_secret", ""))
    if prod_id and prod_secret and not key_store.list_keys(Environment.PRODUCTION):
        key_store.add_key(Environment.PRODUCTION, "main", prod_id, prod_secret, "account:read,trade:read_write")
        logger.info("Seeded production credentials from env vars")

    account_repo = AccountRepo(db)
    account_manager = AccountManager()
    # One-shot v3→v4 data bootstrap (no-op if accounts table already populated).
    await bootstrap_accounts_from_keystore(db, account_repo, key_store)

    # Resolve active account (may be None — fresh install with no keys).
    active_id = await account_repo.get_active_id()
    active_row = await account_repo.get(active_id) if active_id else None

    # Decide endpoint + credentials based on active account, falling back to
    # the legacy env-based URL if there's no active account yet.
    if active_row:
        endpoint_cfg = resolve_endpoint(active_row["endpoint"])
        ws_url = endpoint_cfg.ws_url
        # Keep env_manager loosely in sync so legacy paths still emit the
        # right env label until they migrate to account_manager.
        env_manager.set_env(
            Environment.PRODUCTION if endpoint_cfg.is_production
            else Environment.TESTNET
        )
        active_account_obj = Account(
            id=active_row["id"],
            alias=active_row["alias"],
            endpoint=active_row["endpoint"],
            client_id=active_row["client_id"],
            created_at=active_row["created_at"],
            last_used_at=active_row["last_used_at"],
        )
        account_manager.set_active_unchecked(active_account_obj)
    else:
        ws_url = env_manager.ws_url
        active_account_obj = None

    client = DeribitClient(ws_url)
    if active_row:
        # Connect + authenticate the active account.
        await client.connect()
        try:
            secret_plain = key_store.decrypt(active_row["client_secret"])
            await client.authenticate(active_row["client_id"], secret_plain)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to authenticate active account %s on startup",
                active_row["alias"],
            )
        # Touch last_used to mark this boot.
        await account_repo.touch_last_used(active_row["id"], int(time.time() * 1000))
    else:
        logger.warning(
            "No active account on boot — skipping WebSocket connect. "
            "Configure an account via /api/v1/accounts before trading."
        )

    # Services — pass account_manager so per-account writes use the active
    # account UUID rather than env_manager.current_env (which is a string
    # shared across all accounts on the same env).
    market_data = MarketDataService(client)
    trading = TradingService(client, env_manager, db, account_manager=account_manager)
    portfolio = PortfolioService(client, env_manager, db, account_manager=account_manager)

    # Start equity tracking (writes portfolio snapshots to DB) — only when
    # we actually have a live, authenticated client.
    if active_row:
        await portfolio.start_tracking("BTC")
        await portfolio.start_tracking("ETH")

    # Smart order engine
    smart_engine = SmartOrderEngine(client)
    if active_row:
        await smart_engine.start()
    trading.set_smart_engine(smart_engine)

    # Order monitor — bind to env derived from active endpoint when present.
    monitor_env = env
    if active_row:
        endpoint_cfg = resolve_endpoint(active_row["endpoint"])
        monitor_env = (
            Environment.PRODUCTION if endpoint_cfg.is_production
            else Environment.TESTNET
        )
    order_monitor = OrderMonitor(client, db, env=monitor_env, account_manager=account_manager)

    # Connect order monitor to smart engine
    def _on_order_change(event: str, data: dict) -> None:
        order_id = data.get("order_id", "")
        state = data.get("order_state", "")
        if state == "cancelled":
            smart_engine.notify_order_cancelled(order_id)

    def _on_trade(event: str, data: dict) -> None:
        order_id = data.get("order_id", "")
        price = data.get("price", 0)
        amount = data.get("amount", 0)
        if order_id:
            smart_engine.notify_fill(order_id, price, amount)

    order_monitor.on_order_change(_on_order_change)
    order_monitor.on_trade(_on_trade)

    # Auto-subscribe to all order/trade events (only when authenticated).
    if active_row:
        await order_monitor.subscribe_currency("any")

    # Risk manager
    risk_manager = RiskManager(RiskConfig(
        daily_loss_limit_usd=float(os.getenv("RISK_DAILY_LOSS_LIMIT", "5000")),
        max_order_size_usd=float(os.getenv("RISK_MAX_ORDER_SIZE", "100000")),
    ))
    risk_manager.set_portfolio_service(portfolio)
    risk_manager.set_smart_engine(smart_engine)
    trading.set_risk_manager(risk_manager)
    smart_engine.set_risk_manager(risk_manager)
    await risk_manager.start_periodic_check()

    # Market data recorder — only when connected.
    recorder = MarketDataRecorder(client, db, env=monitor_env)
    if active_row:
        default_instruments = os.getenv(
            "DERIBIT_RECORD_INSTRUMENTS", "BTC-PERPETUAL,ETH-PERPETUAL"
        ).split(",")
        await recorder.start_recording(
            [i.strip() for i in default_instruments if i.strip()]
        )

    return ServiceContainer(
        client=client,
        env_manager=env_manager,
        db=db,
        market_data=market_data,
        trading=trading,
        portfolio=portfolio,
        smart_engine=smart_engine,
        order_monitor=order_monitor,
        risk_manager=risk_manager,
        key_store=key_store,
        account_manager=account_manager,
        account_repo=account_repo,
    )


def _create_app_with_ws(container: ServiceContainer):
    """Create REST app and wire WebSocket broadcast to event sources."""
    app = create_rest_app(
        container.market_data,
        container.trading,
        container.portfolio,
        container.env_manager,
        container.smart_engine,
        container.risk_manager,
        MarketCandleRepo(container.db),
        container=container,
    )

    broadcast = app.state.broadcast

    # Bridge SmartOrder events → WS
    async def _on_smart_order_event(so_id: str, data: dict) -> None:
        await broadcast("smart_order", data)
    container.smart_engine.on_event(_on_smart_order_event)

    # Bridge OrderMonitor events → WS
    async def _on_order_ws(event: str, data: dict) -> None:
        await broadcast("order", data)
    async def _on_trade_ws(event: str, data: dict) -> None:
        await broadcast("trade", data)
    container.order_monitor.on_order_change(_on_order_ws)
    container.order_monitor.on_trade(_on_trade_ws)

    return app


async def run_api_mode(container: ServiceContainer, host: str, port: int) -> None:
    """Run REST API server."""
    import uvicorn

    app = _create_app_with_ws(container)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_mcp_mode(container: ServiceContainer) -> None:
    """Run MCP server over stdio."""
    await run_mcp_server(
        container.market_data,
        container.trading,
        container.portfolio,
        container.env_manager,
        container.smart_engine,
    )


async def run_all_mode(container: ServiceContainer, host: str, port: int) -> None:
    """Run both MCP and REST API concurrently."""
    import uvicorn

    app = _create_app_with_ws(container)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    api_server = uvicorn.Server(config)

    await asyncio.gather(
        run_mcp_mode(container),
        api_server.serve(),
    )


async def async_main(args: argparse.Namespace) -> None:
    env = Environment(args.env)
    container = await build_container(env)

    try:
        if args.mode == "mcp":
            await run_mcp_mode(container)
        elif args.mode == "api":
            await run_api_mode(container, args.host, args.port)
        elif args.mode == "all":
            await run_all_mode(container, args.host, args.port)
    finally:
        await container.risk_manager.stop_periodic_check()
        await container.smart_engine.stop()
        await container.client.disconnect()
        await container.db.close()


def main() -> None:
    # Load .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Deribit Trading System",
        prog="python -m deribit_trading",
    )
    parser.add_argument(
        "mode",
        choices=["mcp", "api", "all"],
        help="mcp: MCP server (stdio), api: REST API (HTTP), all: both",
    )
    parser.add_argument(
        "--env",
        choices=["production", "testnet"],
        default="testnet",
        help="Trading environment (default: testnet)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="REST API host")
    parser.add_argument("--port", type=int, default=8000, help="REST API port")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
