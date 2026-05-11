"""MCP Server exposing trading system tools to AI assistants.

Atomic data plane (Phase 1, read-only): minimal data fetchers + one compute tool.
Heavier analytics (IV skew, term structure, payoff sweeps) belong in the future
Skill layer, not here.
"""

import json
import time
from datetime import datetime, timezone
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import EnvManager, Environment
from .models import InstrumentKind, parse_instrument_kind
from .persistence.repositories import MarketCandleRepo
from .services import MarketDataService, PortfolioService, TradingService
from .models import OrderType
from .smart_order.engine import SmartOrderEngine
from .smart_order.types import SmartOrderConfig


# Deribit TradingView API resolution mapping (kept in sync with rest_api.py).
_RES_TO_DERIBIT = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "1D",
}

# Period to milliseconds mapping for candle queries.
_PERIOD_MS = {
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "7d": 604_800_000,
    "30d": 2_592_000_000,
    "90d": 7_776_000_000,
}

_MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Deribit public fee defaults (BTC/ETH perp + options). Real fees may differ
# per VIP tier; these are the public table values.
_FEES_DEFAULT = {
    "perp_maker": -0.0001,
    "perp_taker": 0.0005,
    "option_maker_btc_per_contract": 0.0003,
    "option_taker_btc_per_contract": 0.0003,
}

_PROCESS_START_MS = int(time.time() * 1000)


def _format_expiry(ts_ms: int) -> str:
    """Format ms timestamp -> '27JUN26' (DDMMMYY)."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return f"{dt.day:02d}{_MONTH_ABBR[dt.month - 1]}{dt.year % 100:02d}"


def _dte(ts_ms: int) -> int:
    """Days to expiry, integer floor."""
    now_ms = int(time.time() * 1000)
    return max(0, (ts_ms - now_ms) // 86_400_000)


def _spread_bps(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return (ask - bid) / mid * 10000


def _mid(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def _json_text(data: Any) -> list[TextContent]:
    """Format data as JSON text content."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def create_mcp_server(
    market_data: MarketDataService,
    trading: TradingService,
    portfolio: PortfolioService,
    env_manager: EnvManager,
    smart_engine: SmartOrderEngine | None = None,
    candle_repo: MarketCandleRepo | None = None,
) -> Server:
    """Create and configure the MCP server with all tools."""

    server = Server("deribit-trading")

    # ── Tool definitions ────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            # ── Discovery (2) ─────────────────────────────────────
            Tool(
                name="list_instruments",
                description=(
                    "List instruments for a currency. Returns minimal "
                    "{instrument_name, expiration_timestamp, strike, option_type}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "BTC or ETH"},
                        "kind": {
                            "type": "string",
                            "enum": ["option", "future", "perpetual"],
                            "description": "Filter (omit for all kinds).",
                        },
                    },
                    "required": ["currency"],
                },
            ),
            Tool(
                name="list_expiries",
                description=(
                    "List option expiries for a currency. Returns "
                    "[{expiry: '27JUN26', dte, timestamp}] sorted ascending."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "BTC or ETH"},
                    },
                    "required": ["currency"],
                },
            ),
            # ── Single instrument (3) ─────────────────────────────
            Tool(
                name="get_quote",
                description=(
                    "Quote for a single instrument; type-adaptive return: "
                    "perp -> {bid, ask, last, mid, spread_bps, mark, funding_8h, change_24h}; "
                    "option -> {bid, ask, last, mid, spread_bps, mark, iv, delta, gamma, vega, theta, underlying}; "
                    "future -> {bid, ask, last, mid, spread_bps, mark, basis, expiration}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument": {
                            "type": "string",
                            "description": "BTC-PERPETUAL / BTC-27JUN26 / BTC-27JUN26-70000-C",
                        },
                    },
                    "required": ["instrument"],
                },
            ),
            Tool(
                name="get_orderbook",
                description=(
                    "Order book depth for one instrument. Returns "
                    "{bids: [[price, size], ...], asks: [[price, size], ...], timestamp}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument": {"type": "string"},
                        "depth": {
                            "type": "integer",
                            "default": 10,
                            "description": "Levels per side (1-1000).",
                        },
                    },
                    "required": ["instrument"],
                },
            ),
            Tool(
                name="get_candles",
                description=(
                    "OHLCV history. Returns array of {timestamp, open, high, low, close, volume}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument": {
                            "type": "string",
                            "default": "BTC-PERPETUAL",
                            "description": "e.g. BTC-PERPETUAL, ETH-PERPETUAL, BTC-27JUN26",
                        },
                        "resolution": {
                            "type": "string",
                            "enum": ["1m", "5m", "15m", "1h", "4h", "1d"],
                            "default": "1m",
                        },
                        "period": {
                            "type": "string",
                            "enum": ["1h", "4h", "1d", "7d", "30d", "90d"],
                            "default": "1h",
                        },
                    },
                },
            ),
            # ── Batch (1) ─────────────────────────────────────────
            Tool(
                name="get_market_snapshot",
                description=(
                    "One-RTT batch snapshot of all instruments for a currency via "
                    "public/get_book_summary_by_currency. Returns array of "
                    "{instrument_name, mid_price, mark_iv, volume_24h, open_interest, "
                    "bid_price, ask_price, underlying_price, mark_price}. "
                    "Default kind='option'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "BTC or ETH"},
                        "kind": {
                            "type": "string",
                            "enum": ["option", "future", "perpetual"],
                            "default": "option",
                            "description": "Filter; pass empty/null to include all kinds.",
                        },
                    },
                    "required": ["currency"],
                },
            ),
            # ── Account (4) ───────────────────────────────────────
            Tool(
                name="get_positions",
                description=(
                    "Open positions. Returns array of "
                    "{instrument, size, direction, entry_price, mark_price, delta, "
                    "pnl_btc, pnl_usd, leverage}. Omit currency to combine BTC + ETH."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "BTC or ETH"},
                    },
                },
            ),
            Tool(
                name="get_balance",
                description=(
                    "Account balance + margin. Returns "
                    "{equity, balance, available, margin_used, im_ratio, mm_ratio, total_pnl}. "
                    "Omit currency to combine BTC + ETH."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "BTC or ETH"},
                    },
                },
            ),
            Tool(
                name="get_pnl_breakdown",
                description=(
                    "PnL by instrument sorted by |total_pnl| desc. Returns array of "
                    "{instrument, total_pnl, pct_of_total}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "currency": {"type": "string", "description": "BTC or ETH"},
                    },
                },
            ),
            Tool(
                name="get_risk_status",
                description=(
                    "Risk-manager state. Returns "
                    "{daily_pnl, daily_limit, paused, max_position_size, current_order_rate}."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            # ── System (1) ────────────────────────────────────────
            Tool(
                name="get_system_status",
                description=(
                    "System / connection state. Returns "
                    "{env, connected, authenticated, ws_url, fees: {maker, taker}, uptime_sec}."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            # ── Compute (1) ───────────────────────────────────────
            Tool(
                name="analyze_option_combo",
                description=(
                    "Analyze a multi-leg option+future combination: payoff curve, "
                    "max profit/loss, breakeven, aggregate Greeks. Pure computation "
                    "(no live data fetch beyond resolving prices)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "legs": {
                            "type": "array",
                            "description": "List of legs (options or futures).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "instrument": {
                                        "type": "string",
                                        "description": "Options BTC-27JUN26-70000-C; futures BTC-PERPETUAL or BTC-27JUN26.",
                                    },
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
            # ── Smart-order list (kept for engine console; not in agent whitelist) ──
            Tool(
                name="list_smart_orders",
                description="List active smart orders.",
                inputSchema={"type": "object", "properties": {}},
            ),
            # ── Write tools (Phase 3; kept implementation, agent excludes them) ───
            Tool(
                name="place_order",
                description="Place a buy or sell order.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument_name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["buy", "sell"]},
                        "amount": {"type": "number"},
                        "order_type": {"type": "string", "enum": ["limit", "market"], "default": "limit"},
                        "price": {"type": "number"},
                        "label": {"type": "string"},
                    },
                    "required": ["instrument_name", "direction", "amount"],
                },
            ),
            Tool(
                name="cancel_order",
                description="Cancel an order by ID.",
                inputSchema={
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
            ),
            Tool(
                name="smart_order",
                description="Create a smart order (auto chasing + fee optimization).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instrument_name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["buy", "sell"]},
                        "amount": {"type": "number"},
                        "algorithm": {"type": "string", "default": "tick-chaser"},
                        "patience": {"type": "number", "default": 0.5},
                        "price_limit": {"type": "number"},
                        "timeout_ms": {"type": "integer", "default": 120000},
                        "prefer_maker": {"type": "boolean", "default": True},
                    },
                    "required": ["instrument_name", "direction", "amount"],
                },
            ),
            Tool(
                name="cancel_smart_order",
                description="Cancel a smart order by ID.",
                inputSchema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            ),
            Tool(
                name="switch_env",
                description="Switch between production and testnet.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "env": {"type": "string", "enum": ["production", "testnet"]},
                    },
                    "required": ["env"],
                },
            ),
        ]

    # ── Helpers (closures over services) ─────────────────────────────

    async def _list_instruments(currency: str, kind: str | None) -> list[dict[str, Any]]:
        ik: InstrumentKind | None = None
        if kind == "option":
            ik = InstrumentKind.OPTION
        elif kind == "future":
            ik = InstrumentKind.FUTURE
        elif kind == "perpetual":
            # Deribit treats perpetual as a future without expiration; fetch
            # all futures and filter to those without expiry.
            ik = InstrumentKind.FUTURE
        items = await trading._client.get_instruments(currency, ik)
        if kind == "perpetual":
            items = [i for i in items if i.expiration_timestamp is None]
        elif kind == "future":
            items = [i for i in items if i.expiration_timestamp is not None]
        out: list[dict[str, Any]] = []
        for inst in items:
            entry: dict[str, Any] = {"instrument_name": inst.instrument_name}
            if inst.expiration_timestamp is not None:
                entry["expiration_timestamp"] = inst.expiration_timestamp
            if inst.strike is not None:
                entry["strike"] = inst.strike
            if inst.option_type is not None:
                entry["option_type"] = inst.option_type
            out.append(entry)
        return out

    async def _list_expiries(currency: str) -> list[dict[str, Any]]:
        items = await trading._client.get_instruments(currency, InstrumentKind.OPTION)
        seen: set[int] = set()
        for inst in items:
            if inst.expiration_timestamp is not None:
                seen.add(inst.expiration_timestamp)
        sorted_ts = sorted(seen)
        return [
            {"expiry": _format_expiry(ts), "dte": _dte(ts), "timestamp": ts}
            for ts in sorted_ts
        ]

    async def _get_quote(instrument: str) -> dict[str, Any]:
        ticker = await market_data.get_ticker(instrument)
        kind = parse_instrument_kind(instrument)
        bid = ticker.best_bid_price
        ask = ticker.best_ask_price
        common: dict[str, Any] = {
            "instrument": instrument,
            "kind": kind,
            "bid": bid,
            "ask": ask,
            "last": ticker.last_price,
            "mid": _mid(bid, ask),
            "spread_bps": _spread_bps(bid, ask),
            "mark": ticker.mark_price,
        }
        if kind == "perpetual":
            common["funding_8h"] = ticker.funding_8h
            common["change_24h"] = ticker.price_change_24h
        elif kind == "option":
            g = ticker.greeks
            common.update(
                iv=ticker.implied_volatility,
                delta=g.delta if g else None,
                gamma=g.gamma if g else None,
                vega=g.vega if g else None,
                theta=g.theta if g else None,
                underlying=ticker.underlying_price,
            )
        elif kind == "future":
            mark = ticker.mark_price
            idx = ticker.index_price
            common["basis"] = (mark - idx) if (mark is not None and idx is not None) else None
            # Resolve expiration via instrument metadata if cheap; leave None
            # otherwise (LLM can infer from the name suffix).
            common["expiration"] = None
        return common

    async def _get_orderbook(instrument: str, depth: int) -> dict[str, Any]:
        raw = await market_data.get_orderbook(instrument, depth)
        return {
            "bids": raw.get("bids", []),
            "asks": raw.get("asks", []),
            "timestamp": raw.get("timestamp"),
        }

    async def _get_market_snapshot(currency: str, kind: str | None) -> list[dict[str, Any]]:
        rows = await trading._client.get_book_summary_by_currency(currency, kind=kind)
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "instrument_name": r.get("instrument_name"),
                "mid_price": r.get("mid_price"),
                "mark_iv": r.get("mark_iv"),
                "volume_24h": r.get("volume"),
                "open_interest": r.get("open_interest"),
                "bid_price": r.get("bid_price"),
                "ask_price": r.get("ask_price"),
                "underlying_price": r.get("underlying_price"),
                "mark_price": r.get("mark_price"),
            })
        return out

    async def _positions_for_currency(currency: str) -> list[dict[str, Any]]:
        positions = await trading._client.get_positions(currency)
        out: list[dict[str, Any]] = []
        for p in positions:
            if p.size <= 0:
                continue
            mark = p.mark_price
            entry = p.average_price
            pnl_native = p.total_profit_loss
            # USD value: for inverse contracts size is in USD notional already
            # (BTC perp $10/contract * contracts), but Deribit returns size in
            # USD for perp/future and contracts for options. We surface the
            # native PnL and let the caller convert if needed.
            out.append({
                "instrument": p.instrument_name,
                "size": p.size,
                "direction": p.direction,
                "entry_price": entry,
                "mark_price": mark,
                "delta": p.delta,
                "pnl_btc": pnl_native,
                "pnl_usd": (pnl_native * mark) if (mark and pnl_native is not None) else None,
                "leverage": p.leverage,
            })
        return out

    async def _balance_for_currency(currency: str) -> dict[str, Any]:
        account = await trading._client.get_account_summary(currency)
        equity = account.equity or 0.0
        im = account.initial_margin or 0.0
        mm = account.maintenance_margin or 0.0
        return {
            "currency": currency,
            "equity": equity,
            "balance": account.balance,
            "available": account.available_funds,
            "margin_used": im,
            "im_ratio": (im / equity) if equity else None,
            "mm_ratio": (mm / equity) if equity else None,
            "total_pnl": account.total_pl,
        }

    async def _get_positions(currency: str | None) -> list[dict[str, Any]]:
        if currency:
            return await _positions_for_currency(currency)
        out: list[dict[str, Any]] = []
        for ccy in ("BTC", "ETH"):
            out.extend(await _positions_for_currency(ccy))
        return out

    async def _get_balance(currency: str | None) -> Any:
        if currency:
            return await _balance_for_currency(currency)
        return {ccy: await _balance_for_currency(ccy) for ccy in ("BTC", "ETH")}

    async def _get_pnl_breakdown(currency: str | None) -> list[dict[str, Any]]:
        if currency:
            attribution = await portfolio.get_pnl_attribution(currency)
        else:
            attribution = []
            for ccy in ("BTC", "ETH"):
                attribution.extend(await portfolio.get_pnl_attribution(ccy))
        attribution.sort(key=lambda x: abs(x.get("total_pnl", 0) or 0), reverse=True)
        total = sum(abs(x.get("total_pnl", 0) or 0) for x in attribution) or 1.0
        return [
            {
                "instrument": x["instrument"],
                "total_pnl": x.get("total_pnl"),
                "pct_of_total": (abs(x.get("total_pnl", 0) or 0) / total) * 100.0,
            }
            for x in attribution
        ]

    def _get_risk_status() -> dict[str, Any]:
        rm = (
            smart_engine._risk_manager
            if (smart_engine and getattr(smart_engine, "_risk_manager", None))
            else None
        )
        if not rm:
            return {
                "daily_pnl": 0.0,
                "daily_limit": None,
                "paused": False,
                "max_position_size": None,
                "current_order_rate": None,
            }
        s = rm.get_risk_status()
        cfg = s.get("config", {})
        return {
            "daily_pnl": s.get("daily_pnl", 0.0),
            "daily_limit": cfg.get("daily_loss_limit_usd"),
            "paused": s.get("trading_paused", False),
            "max_position_size": cfg.get("max_position_size"),
            "current_order_rate": None,
        }

    def _get_system_status() -> dict[str, Any]:
        client = trading._client
        return {
            "env": env_manager.current_env,
            "connected": getattr(client, "is_connected", False),
            "authenticated": getattr(client, "is_authenticated", False),
            "ws_url": env_manager.ws_url,
            "fees": _FEES_DEFAULT,
            "uptime_sec": (int(time.time() * 1000) - _PROCESS_START_MS) // 1000,
        }

    # ── Tool dispatch ────────────────────────────────────────────────

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            # ── Discovery ────────────────────────────────
            if name == "list_instruments":
                data = await _list_instruments(
                    arguments["currency"], arguments.get("kind")
                )
                return _json_text(data)

            elif name == "list_expiries":
                data = await _list_expiries(arguments["currency"])
                return _json_text(data)

            # ── Single instrument ────────────────────────
            elif name == "get_quote":
                data = await _get_quote(arguments["instrument"])
                return _json_text(data)

            elif name == "get_orderbook":
                data = await _get_orderbook(
                    arguments["instrument"], arguments.get("depth", 10)
                )
                return _json_text(data)

            elif name == "get_candles":
                instrument = arguments.get("instrument", "BTC-PERPETUAL")
                resolution = arguments.get("resolution", "1m")
                period = arguments.get("period", "1h")
                now = int(time.time() * 1000)
                since = now - _PERIOD_MS.get(period, _PERIOD_MS["1h"])

                if candle_repo is not None:
                    try:
                        data = await candle_repo.get_candles(
                            env_manager.current_env, instrument, resolution, since, now
                        )
                        if data:
                            return _json_text(data)
                    except Exception:
                        pass

                deribit_res = _RES_TO_DERIBIT.get(resolution, resolution)
                try:
                    result = await trading._client.call(
                        "public/get_tradingview_chart_data",
                        {
                            "instrument_name": instrument,
                            "start_timestamp": since,
                            "end_timestamp": now,
                            "resolution": deribit_res,
                        },
                    )
                    ticks = result.get("ticks", [])
                    opens = result.get("open", [])
                    highs = result.get("high", [])
                    lows = result.get("low", [])
                    closes = result.get("close", [])
                    volumes = result.get("volume", [])
                    candles = [
                        {
                            "timestamp": ticks[i],
                            "open": opens[i],
                            "high": highs[i],
                            "low": lows[i],
                            "close": closes[i],
                            "volume": volumes[i] if i < len(volumes) else 0,
                        }
                        for i in range(len(ticks))
                    ]
                    return _json_text(candles)
                except Exception as exc:  # noqa: BLE001
                    return _json_text({
                        "error": f"Failed to fetch candles for {instrument}: {type(exc).__name__}: {exc}",
                        "instrument": instrument,
                        "resolution": resolution,
                        "period": period,
                    })

            # ── Batch ──────────────────────────────────────
            elif name == "get_market_snapshot":
                kind = arguments.get("kind", "option")
                if kind == "":
                    kind = None
                data = await _get_market_snapshot(arguments["currency"], kind)
                return _json_text(data)

            # ── Account ────────────────────────────────────
            elif name == "get_positions":
                data = await _get_positions(arguments.get("currency"))
                return _json_text(data)

            elif name == "get_balance":
                data = await _get_balance(arguments.get("currency"))
                return _json_text(data)

            elif name == "get_pnl_breakdown":
                data = await _get_pnl_breakdown(arguments.get("currency"))
                return _json_text(data)

            elif name == "get_risk_status":
                return _json_text(_get_risk_status())

            # ── System ─────────────────────────────────────
            elif name == "get_system_status":
                return _json_text(_get_system_status())

            # ── Compute ────────────────────────────────────
            elif name == "analyze_option_combo":
                import httpx
                legs = arguments.get("legs", [])
                try:
                    body = {"legs": legs}
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            "http://localhost:8000/api/v1/options/payoff",
                            json=body,
                            timeout=30,
                        )
                        result = resp.json()

                    s = result.get("summary", {})
                    legs_info = result.get("legs", [])

                    text = "Option+Futures Combo Analysis\n"
                    text += f"{'='*40}\n\n"
                    text += "Legs:\n"
                    for l in legs_info:
                        if l.get("type") == "future":
                            text += (
                                f"  {l['direction'].upper()} {l['instrument']} "
                                f"x{l['amount']} (entry: {l.get('entry_price', 0):,.0f})\n"
                            )
                        else:
                            text += (
                                f"  {l['direction'].upper()} {l['instrument']} "
                                f"x{l['amount']} @ {l.get('premium_btc', 0):.4f} BTC\n"
                            )
                    text += "\nPayoff Summary:\n"
                    text += f"  Max Profit: {s['max_profit_btc']:.4f} BTC (${s['max_profit_usd']:,.0f})\n"
                    text += f"  Max Loss:   {s['max_loss_btc']:.4f} BTC (${s['max_loss_usd']:,.0f})\n"
                    text += f"  Breakeven:  {', '.join(f'${b:,.0f}' for b in s.get('breakeven', []))}\n"
                    text += f"  R/R Ratio:  {s['risk_reward_ratio']:.2f}\n"
                    text += "\nGreeks:\n"
                    text += f"  Net Delta: {s['net_delta']:.4f}\n"
                    text += f"  Net Theta: {s['net_theta']:.4f}\n"
                    text += f"  Net Premium: {s['net_premium_btc']:.4f} BTC\n"
                    return [TextContent(type="text", text=text)]
                except Exception as e:  # noqa: BLE001
                    return [TextContent(type="text", text=f"Error: {e}")]

            # ── Smart-order list (engine console) ─────────
            elif name == "list_smart_orders":
                if not smart_engine:
                    return _json_text([])
                return _json_text([so.to_dict() for so in smart_engine.list_orders()])

            # ── Write tools (Phase 3) ─────────────────────
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
                return [TextContent(
                    type="text",
                    text=env_warning + json.dumps(so.to_dict(), indent=2, default=str),
                )]

            elif name == "cancel_smart_order":
                if not smart_engine:
                    return [TextContent(type="text", text="SmartOrderEngine not available")]
                so = await smart_engine.cancel_smart_order(arguments["id"])
                if not so:
                    return [TextContent(
                        type="text",
                        text=f"SmartOrder {arguments['id']} not found",
                    )]
                return _json_text(so.to_dict())

            elif name == "switch_env":
                new_env = Environment(arguments["env"])
                env_manager.set_env(new_env)
                return _json_text({
                    "status": "switched",
                    "env": new_env,
                    "note": "Client reconnection required. Restart the system to apply.",
                })

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:  # noqa: BLE001
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

    return server


async def run_mcp_server(
    market_data: MarketDataService,
    trading: TradingService,
    portfolio: PortfolioService,
    env_manager: EnvManager,
    smart_engine: SmartOrderEngine | None = None,
    candle_repo: MarketCandleRepo | None = None,
) -> None:
    """Run the MCP server over stdio."""
    server = create_mcp_server(
        market_data, trading, portfolio, env_manager, smart_engine, candle_repo
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
