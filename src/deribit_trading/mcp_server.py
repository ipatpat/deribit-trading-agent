"""MCP Server exposing trading system tools to AI assistants."""

import json
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import EnvManager, Environment
from .services import MarketDataService, PortfolioService, TradingService
from .models import OrderType, TimeInForce
from .smart_order.engine import SmartOrderEngine
from .smart_order.types import SmartOrderConfig


def _json_text(data: Any) -> list[TextContent]:
    """Format data as JSON text content."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def create_mcp_server(
    market_data: MarketDataService,
    trading: TradingService,
    portfolio: PortfolioService,
    env_manager: EnvManager,
    smart_engine: SmartOrderEngine | None = None,
) -> Server:
    """Create and configure the MCP server with all tools."""

    server = Server("deribit-trading")

    # ── Tool definitions ────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # Market data
            Tool(
                name="get_ticker",
                description="Get current market data for an instrument (price, volume, Greeks for options, funding rate for perpetuals)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument_name": {"type": "string", "description": "e.g. BTC-PERPETUAL, ETH-27JUN25-3000-C"},
                    },
                    "required": ["instrument_name"],
                },
            ),
            Tool(
                name="get_option_chain",
                description="Get option chain for a currency, optionally filtered by expiry",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "e.g. BTC, ETH"},
                        "expiry_timestamp": {"type": "integer", "description": "Filter by expiry (ms timestamp, optional)"},
                    },
                    "required": ["currency"],
                },
            ),
            Tool(
                name="get_vol_surface",
                description="Get implied volatility surface for a currency ({expiry: {strike: IV}})",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string"},
                    },
                    "required": ["currency"],
                },
            ),
            # Trading
            Tool(
                name="place_order",
                description="Place a buy or sell order. Checks production safety.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument_name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["buy", "sell"]},
                        "amount": {"type": "number"},
                        "order_type": {"type": "string", "enum": ["limit", "market"], "default": "limit"},
                        "price": {"type": "number", "description": "Required for limit orders"},
                        "label": {"type": "string", "description": "Optional order label"},
                    },
                    "required": ["instrument_name", "direction", "amount"],
                },
            ),
            Tool(
                name="cancel_order",
                description="Cancel an order by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                    },
                    "required": ["order_id"],
                },
            ),
            # Portfolio
            Tool(
                name="get_equity_curve",
                description="Get equity curve (net value over time) with automatic bucketing",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "default": "BTC"},
                        "period": {"type": "string", "enum": ["1h", "4h", "1d", "7d", "30d"], "default": "1d"},
                    },
                },
            ),
            Tool(
                name="get_portfolio",
                description="Get current portfolio snapshot: positions, equity, Greeks summary",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "default": "BTC"},
                    },
                },
            ),
            Tool(
                name="get_pnl_attribution",
                description="Get PnL breakdown by instrument, sorted by contribution",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "default": "BTC"},
                    },
                },
            ),
            # Environment
            Tool(
                name="switch_env",
                description="Switch between production and testnet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "env": {"type": "string", "enum": ["production", "testnet"]},
                    },
                    "required": ["env"],
                },
            ),
            Tool(
                name="get_system_status",
                description="Get current system status: environment, connection, subscriptions",
                inputSchema={"type": "object", "properties": {}},
            ),
            # Smart orders
            Tool(
                name="smart_order",
                description="Create a smart order with automatic price chasing and fee optimization",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument_name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["buy", "sell"]},
                        "amount": {"type": "number"},
                        "algorithm": {"type": "string", "default": "tick-chaser"},
                        "patience": {"type": "number", "default": 0.5, "description": "0.0 (aggressive) to 1.0 (patient)"},
                        "price_limit": {"type": "number", "description": "Max price for buy, min for sell"},
                        "timeout_ms": {"type": "integer", "default": 120000},
                        "prefer_maker": {"type": "boolean", "default": True},
                    },
                    "required": ["instrument_name", "direction", "amount"],
                },
            ),
            Tool(
                name="list_smart_orders",
                description="List active smart orders",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="cancel_smart_order",
                description="Cancel a smart order by ID",
                inputSchema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            ),
            Tool(
                name="get_risk_status",
                description="Get current risk status: daily PnL, trading paused state, limits",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="analyze_option_combo",
                description="Analyze a multi-leg option+futures combination: payoff curve, max profit/loss, breakeven, Greeks. Supports options (e.g. BTC-27JUN25-70000-C) and futures (e.g. BTC-PERPETUAL, BTC-27JUN25) for delta hedging.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "legs": {
                            "type": "array",
                            "description": "List of legs. Each leg can be an option (BTC-27JUN25-70000-C) or a future (BTC-PERPETUAL, BTC-27JUN25) for delta hedging.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "instrument": {"type": "string", "description": "Instrument name. Options: BTC-27JUN25-70000-C. Futures: BTC-PERPETUAL or BTC-27JUN25"},
                                    "direction": {"type": "string", "enum": ["buy", "sell"]},
                                    "amount": {"type": "number", "default": 1},
                                },
                                "required": ["instrument", "direction"],
                            },
                        },
                    },
                    "required": ["legs"],
                },
            ),
            Tool(
                name="get_candles",
                description="Get OHLCV candle data for an instrument",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument": {"type": "string", "default": "BTC-PERPETUAL"},
                        "resolution": {"type": "string", "enum": ["1m", "5m", "1h"], "default": "1m"},
                        "period": {"type": "string", "enum": ["1h", "4h", "1d", "7d"], "default": "1h"},
                    },
                },
            ),
        ]

    # ── Tool implementations ────────────────────────────────────────

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "get_ticker":
                ticker = await market_data.get_ticker(arguments["instrument_name"])
                return _json_text(ticker.model_dump())

            elif name == "get_option_chain":
                chain = await market_data.get_option_chain(
                    arguments["currency"],
                    arguments.get("expiry_timestamp"),
                )
                # Summarize for readability
                summary = {}
                for exp, tickers in chain.items():
                    summary[exp] = [
                        {
                            "instrument": t.instrument_name,
                            "last_price": t.last_price,
                            "iv": t.implied_volatility,
                            "delta": t.greeks.delta if t.greeks else None,
                            "bid": t.best_bid_price,
                            "ask": t.best_ask_price,
                        }
                        for t in tickers
                    ]
                return _json_text(summary)

            elif name == "get_vol_surface":
                surface = await market_data.get_vol_surface(arguments["currency"])
                return _json_text(surface)

            elif name == "place_order":
                env_warning = ""
                if env_manager.is_production():
                    env_warning = "⚠️ PRODUCTION ENVIRONMENT - Real funds at risk!\n\n"

                direction = arguments["direction"]
                order_type = OrderType(arguments.get("order_type", "limit"))
                fn = trading.buy if direction == "buy" else trading.sell

                order = await fn(
                    instrument_name=arguments["instrument_name"],
                    amount=arguments["amount"],
                    order_type=order_type,
                    price=arguments.get("price"),
                    label=arguments.get("label"),
                )
                result = env_warning + json.dumps(order.model_dump(), indent=2, default=str)
                return [TextContent(type="text", text=result)]

            elif name == "cancel_order":
                order = await trading.cancel(arguments["order_id"])
                return _json_text(order.model_dump())

            elif name == "get_equity_curve":
                currency = arguments.get("currency", "BTC")
                period = arguments.get("period", "1d")
                period_ms = {
                    "1h": 3_600_000,
                    "4h": 14_400_000,
                    "1d": 86_400_000,
                    "7d": 604_800_000,
                    "30d": 2_592_000_000,
                }
                now = int(time.time() * 1000)
                since = now - period_ms.get(period, 86_400_000)
                curve = await portfolio.get_equity_curve(currency, since, now)
                return _json_text(curve)

            elif name == "get_portfolio":
                currency = arguments.get("currency", "BTC")
                snapshot = await portfolio.get_snapshot(currency)
                return _json_text(snapshot.model_dump())

            elif name == "get_pnl_attribution":
                currency = arguments.get("currency", "BTC")
                attribution = await portfolio.get_pnl_attribution(currency)
                return _json_text(attribution)

            elif name == "switch_env":
                new_env = Environment(arguments["env"])
                env_manager.set_env(new_env)
                return _json_text({
                    "status": "switched",
                    "env": new_env,
                    "note": "Client reconnection required. Restart the system to apply.",
                })

            elif name == "get_system_status":
                from .client import DeribitClient
                return _json_text({
                    "env": env_manager.current_env,
                    "is_production": env_manager.is_production(),
                    "allow_live_trading": env_manager.allow_live_trading,
                    "ws_url": env_manager.ws_url,
                })

            # Smart orders
            elif name == "smart_order":
                if not smart_engine:
                    return [TextContent(type="text", text="SmartOrderEngine not available")]
                env_warning = ""
                if env_manager.is_production():
                    env_warning = "WARNING: PRODUCTION ENVIRONMENT\n\n"
                config = SmartOrderConfig(
                    instrument_name=arguments["instrument_name"],
                    direction=arguments["direction"],
                    amount=arguments["amount"],
                    algorithm=arguments.get("algorithm", "tick-chaser"),
                    price_limit=arguments.get("price_limit"),
                    timeout_ms=arguments.get("timeout_ms", 120000),
                    prefer_maker=arguments.get("prefer_maker", True),
                    patience=arguments.get("patience", 0.5),
                )
                so = await smart_engine.create_smart_order(config)
                return [TextContent(type="text", text=env_warning + json.dumps(so.to_dict(), indent=2, default=str))]

            elif name == "list_smart_orders":
                if not smart_engine:
                    return _json_text([])
                return _json_text([so.to_dict() for so in smart_engine.list_orders()])

            elif name == "cancel_smart_order":
                if not smart_engine:
                    return [TextContent(type="text", text="SmartOrderEngine not available")]
                so = await smart_engine.cancel_smart_order(arguments["id"])
                if not so:
                    return [TextContent(type="text", text=f"SmartOrder {arguments['id']} not found")]
                return _json_text(so.to_dict())

            elif name == "get_risk_status":
                if not smart_engine or not hasattr(smart_engine, '_risk_manager') or not smart_engine._risk_manager:
                    return [TextContent(type="text", text="RiskManager not available")]
                return _json_text(smart_engine._risk_manager.get_risk_status())

            elif name == "get_candles":
                currency = arguments.get("instrument", "BTC-PERPETUAL")
                resolution = arguments.get("resolution", "1m")
                period = arguments.get("period", "1h")
                period_ms = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "7d": 604_800_000}
                now = int(time.time() * 1000)
                since = now - period_ms.get(period, 3_600_000)
                from .persistence.repositories import MarketCandleRepo
                repo = MarketCandleRepo(trading._client if hasattr(trading, '_client') else None)
                # Note: candle query needs DB access, returning placeholder
                return [TextContent(type="text", text=f"Candle query: {currency} {resolution} (use REST API /api/v1/candles for data)")]

            elif name == "analyze_option_combo":
                import httpx
                legs = arguments.get("legs", [])
                try:
                    body = {"legs": legs}
                    async with httpx.AsyncClient() as client:
                        resp = await client.post("http://localhost:8000/api/v1/options/payoff", json=body, timeout=30)
                        result = resp.json()

                    s = result.get("summary", {})
                    legs_info = result.get("legs", [])

                    text = f"Option+Futures Combo Analysis\n"
                    text += f"{'='*40}\n\n"
                    text += f"Legs:\n"
                    for l in legs_info:
                        if l.get("type") == "future":
                            text += f"  {l['direction'].upper()} {l['instrument']} x{l['amount']} (entry: {l.get('entry_price', 0):,.0f})\n"
                        else:
                            text += f"  {l['direction'].upper()} {l['instrument']} x{l['amount']} @ {l.get('premium_btc', 0):.4f} BTC\n"
                    text += f"\nPayoff Summary:\n"
                    text += f"  Max Profit: {s['max_profit_btc']:.4f} BTC (${s['max_profit_usd']:,.0f})\n"
                    text += f"  Max Loss:   {s['max_loss_btc']:.4f} BTC (${s['max_loss_usd']:,.0f})\n"
                    text += f"  Breakeven:  {', '.join(f'${b:,.0f}' for b in s.get('breakeven', []))}\n"
                    text += f"  R/R Ratio:  {s['risk_reward_ratio']:.2f}\n"
                    text += f"\nGreeks:\n"
                    text += f"  Net Delta: {s['net_delta']:.4f}\n"
                    text += f"  Net Theta: {s['net_theta']:.4f}\n"
                    text += f"  Net Premium: {s['net_premium_btc']:.4f} BTC\n"

                    return [TextContent(type="text", text=text)]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error: {e}")]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

    return server


async def run_mcp_server(
    market_data: MarketDataService,
    trading: TradingService,
    portfolio: PortfolioService,
    env_manager: EnvManager,
    smart_engine: SmartOrderEngine | None = None,
) -> None:
    """Run the MCP server over stdio."""
    server = create_mcp_server(market_data, trading, portfolio, env_manager, smart_engine)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
