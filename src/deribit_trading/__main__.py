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
from .config import EnvManager, Environment, KeyStore
from .mcp_server import run_mcp_server
from .persistence import Database
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
        self._start_time = time.time()

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

    # Client
    client = DeribitClient(env_manager.ws_url)
    await client.connect()

    # Authenticate if credentials available
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

    # Authenticate with current env's key
    keys = key_store.list_keys(env)
    if keys:
        key = key_store.get_key(env, keys[0].name)
        if key:
            await client.authenticate(key.client_id, key.client_secret)
    else:
        # Last fallback: generic env vars
        fallback_id = os.getenv("DERIBIT_CLIENT_ID", "")
        fallback_secret = os.getenv("DERIBIT_CLIENT_SECRET", "")
        if fallback_id and fallback_secret:
            await client.authenticate(fallback_id, fallback_secret)

    # Services
    market_data = MarketDataService(client)
    trading = TradingService(client, env_manager, db)
    portfolio = PortfolioService(client, env_manager, db)

    # Start equity tracking (writes portfolio snapshots to DB)
    await portfolio.start_tracking("BTC")
    await portfolio.start_tracking("ETH")

    # Smart order engine
    smart_engine = SmartOrderEngine(client)
    await smart_engine.start()
    trading.set_smart_engine(smart_engine)

    # Order monitor
    order_monitor = OrderMonitor(client, db, env=env)

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

    # Auto-subscribe to all order/trade events
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

    # Market data recorder
    recorder = MarketDataRecorder(client, db, env=env)
    default_instruments = os.getenv(
        "DERIBIT_RECORD_INSTRUMENTS", "BTC-PERPETUAL,ETH-PERPETUAL"
    ).split(",")
    await recorder.start_recording([i.strip() for i in default_instruments if i.strip()])

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
