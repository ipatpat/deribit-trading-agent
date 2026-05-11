"""MCP -> OpenAI tool def conversion + read-only whitelist + description override.

Phase 1 exposes the atomic-redesign data plane (12 read-only data tools +
1 compute tool) to the agent. The 5 write tools — place_order, cancel_order,
smart_order, cancel_smart_order, switch_env — stay disabled until Phase 3.

Tool descriptions are *overridden* at the agent layer so the LLM sees a rich
"when to use me" prompt; the original MCP server descriptions stay short for
IDE / MCP-stdio consumers.
"""

from __future__ import annotations

from typing import Any

# ── Phase 1 read-only whitelist (12 atomic tools) ────────────────────────────
PHASE_1_READ_ONLY_TOOLS: list[str] = [
    # Discovery (2)
    "list_instruments",
    "list_expiries",
    # Single instrument (3)
    "get_quote",
    "get_orderbook",
    "get_candles",
    # Batch (1)
    "get_market_snapshot",
    # Account (4)
    "get_positions",
    "get_balance",
    "get_pnl_breakdown",
    "get_risk_status",
    # System (1)
    "get_system_status",
    # Compute (1)
    "analyze_option_combo",
]

# Excluded from Phase 1 — write tools that mutate account state. Phase 3 will
# introduce them with a confirmation card flow.
WRITE_TOOLS: list[str] = [
    "place_order",
    "cancel_order",
    "smart_order",
    "cancel_smart_order",
    "switch_env",
]


# ── Description overrides ────────────────────────────────────────────────────
# Each description follows a 4-section structure (purpose / fields / when to
# use vs swap / example prompt) and is ≥ 250 characters.
TOOL_DESCRIPTIONS_OVERRIDE: dict[str, str] = {
    "list_instruments": (
        "Discovery tool that returns the lightweight catalogue of Deribit "
        "instruments for a currency. Each entry contains only "
        "{instrument_name, expiration_timestamp?, strike?, option_type?} — "
        "tick_size / contract_size and other metadata are intentionally "
        "omitted; fetch them only when strictly required for sizing math. "
        "Use this to enumerate every option / future / perp before drilling "
        "into specific names; for live prices on those names switch to "
        "get_market_snapshot (batch) or get_quote (single). Example prompt: "
        "'What ETH options are listed?' → list_instruments(currency='ETH', "
        "kind='option'). Pass kind to filter; omit kind to receive all "
        "instruments of the currency."
    ),
    "list_expiries": (
        "Returns the sorted list of option expiries for a currency as "
        "[{expiry: '27JUN26', dte, timestamp}], deduplicated and ascending. "
        "Use this whenever the user asks about 'nearest expiry', 'monthly "
        "expiries', or you need to choose a tenor before fetching strikes. "
        "Pair with get_market_snapshot(kind='option') and filter client-side "
        "by timestamp to scope a chain to one expiry. Do NOT use it for "
        "futures expiries — those are obvious from list_instruments(kind="
        "'future'). Example prompt: 'What's the nearest BTC option expiry?' "
        "→ list_expiries(currency='BTC')."
    ),
    "get_quote": (
        "Live quote for a SINGLE instrument. The return shape adapts to the "
        "instrument kind: perp -> {bid, ask, last, mid, spread_bps, mark, "
        "funding_8h, change_24h}; option -> {bid, ask, last, mid, "
        "spread_bps, mark, iv, delta, gamma, vega, theta, underlying}; "
        "future -> {bid, ask, last, mid, spread_bps, mark, basis, "
        "expiration}. Use this when the user asks about ONE instrument by "
        "name (price check, single-strike Greeks, single perp funding). "
        "For batch comparisons across many strikes/expiries use "
        "get_market_snapshot instead — calling get_quote in a loop is "
        "wasteful. Example prompt: 'BTC perp price?' → "
        "get_quote(instrument='BTC-PERPETUAL')."
    ),
    "get_orderbook": (
        "Order-book depth for a single instrument. Returns "
        "{bids: [[price, size], ...], asks: [[price, size], ...], "
        "timestamp}; bids descending, asks ascending. Use this when the user "
        "asks about liquidity, slippage, or wants to see a multi-level "
        "ladder before sizing a trade. For just the top-of-book price + "
        "spread, get_quote is cheaper. Optional. Omit if unknown. Default "
        "depth is 10 levels per side; pass a larger depth (up to 1000) only "
        "when the user explicitly wants deep book analysis. Example prompt: "
        "'How deep is the book on BTC perp?' → "
        "get_orderbook(instrument='BTC-PERPETUAL', depth=20)."
    ),
    "get_candles": (
        "OHLCV history for an instrument over a time window. Returns an "
        "array of {timestamp, open, high, low, close, volume}. Resolution "
        "options: '1m' (scalp), '5m'/'15m' (intraday), '1h' (daily swing), "
        "'4h'/'1d' (trend). Period options: '1h', '4h', '1d', '7d', '30d', "
        "'90d'. Pick the smallest resolution × period that answers the "
        "question — never request 90d at 1m. Use this for charting, vol "
        "estimation, or trend questions; for a current price snapshot prefer "
        "get_quote. Optional. Omit if unknown. Defaults: instrument='BTC-"
        "PERPETUAL', resolution='1m', period='1h'."
    ),
    "get_market_snapshot": (
        "PREFERRED tool for any 'how is the X market', 'all options on Y', "
        "or chain-level question. One ~200ms RTT to "
        "public/get_book_summary_by_currency returns a single array of "
        "{instrument_name, mid_price, mark_iv, volume_24h, open_interest, "
        "bid_price, ask_price, underlying_price, mark_price} for every "
        "instrument in the currency. Use this BEFORE drilling into "
        "individual strikes — find the active expiries / strikes here in "
        "one shot. For a single instrument's deeper data (Greeks, spread "
        "analysis) follow up with get_quote(instrument). Optional. Omit if "
        "unknown. Default kind='option' (most common); pass 'future' / "
        "'perpetual' to scope; pass empty string '' to include everything."
    ),
    "get_positions": (
        "Open positions across the user's account. Returns an array of "
        "{instrument, size, direction, entry_price, mark_price, delta, "
        "pnl_btc, pnl_usd, leverage} ordered by Deribit's default. Use this "
        "whenever the question depends on current exposure: 'where am I "
        "long?', 'show my positions', 'what's my net delta?'. For balance / "
        "margin numbers use get_balance; for PnL ranking use "
        "get_pnl_breakdown. Optional. Omit if unknown. Pass currency to "
        "filter (BTC or ETH); omit to combine BTC + ETH subaccounts. "
        "Example prompt: 'Show my open positions' → get_positions()."
    ),
    "get_balance": (
        "Account balance and margin snapshot. Returns "
        "{equity, balance, available, margin_used, im_ratio, mm_ratio, "
        "total_pnl}. Use this when the user asks about equity, available "
        "capital, margin usage, or session-cumulative P&L. For the per-"
        "position P&L breakdown use get_pnl_breakdown; for risk-limit state "
        "use get_risk_status. Optional. Omit if unknown. Pass currency to "
        "scope (BTC or ETH); omit to receive a per-currency dict combining "
        "both. Example prompt: 'What's my BTC equity?' → "
        "get_balance(currency='BTC')."
    ),
    "get_pnl_breakdown": (
        "P&L attribution by instrument, sorted descending by absolute "
        "contribution. Returns array of {instrument, total_pnl, "
        "pct_of_total}. Use this when the user asks 'which positions are "
        "driving my P&L?', 'what's hurting me most?', or wants a ranked "
        "view. For aggregate equity / session P&L use get_balance instead. "
        "Optional. Omit if unknown. Pass currency to scope; omit to combine "
        "BTC + ETH. Example prompt: 'What's driving today's P&L?' → "
        "get_pnl_breakdown()."
    ),
    "get_risk_status": (
        "Risk-manager state. Returns {daily_pnl, daily_limit, paused, "
        "max_position_size, current_order_rate}. Use this when the user "
        "asks 'am I close to the daily loss limit', 'is trading paused', "
        "or 'what's my max position size'. For balance / equity use "
        "get_balance; for risk numbers tied to specific positions use "
        "get_positions. No parameters. Example prompt: 'Am I near my daily "
        "loss limit?' → get_risk_status()."
    ),
    "get_system_status": (
        "System / connection state. Returns "
        "{env, connected, authenticated, ws_url, fees: {maker, taker}, "
        "uptime_sec}. Use this to verify connectivity before trusting other "
        "results, to confirm production-vs-testnet before discussing "
        "trades, or to look up current fee schedule. The fees field is the "
        "Deribit public default (perp maker/taker, options per-contract); "
        "VIP tiers may differ. No parameters. Example prompt: 'Am I "
        "connected to mainnet?' → get_system_status()."
    ),
    "analyze_option_combo": (
        "Pure-computation tool: given a list of legs, return payoff curve, "
        "max profit, max loss, breakeven points, and aggregate Greeks. Each "
        "leg is {instrument, direction, amount}; mix options "
        "(BTC-27JUN26-70000-C) with futures (BTC-PERPETUAL or BTC-27JUN26) "
        "for delta hedging. Use this for ANY 'what-if' strategy analysis "
        "before discussing trade-offs — straddle, condor, covered call, "
        "calendar, spread, hedge. No live data is fetched beyond resolving "
        "current prices for valuation; this is an analytics call, not a "
        "market query. Direction must be 'buy' or 'sell'; amount defaults "
        "to 1 if omitted."
    ),
}


# ── Conversion: MCP Tool -> OpenAI tool def ──────────────────────────────────
def convert_mcp_to_openai(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP Tool objects to OpenAI function tool definitions.

    Filters by PHASE_1_READ_ONLY_TOOLS whitelist, applies description overrides,
    annotates optional parameters with "Optional. Omit if unknown." prefix
    (GLM-4.6 / DeepSeek fail-fast defense).

    Args:
        mcp_tools: list of MCP Tool objects with .name, .description, .inputSchema

    Returns:
        OpenAI tool defs: [{"type": "function", "function": {name, description, parameters}}, ...]
    """
    out: list[dict[str, Any]] = []
    whitelist = set(PHASE_1_READ_ONLY_TOOLS)
    for tool in mcp_tools:
        if tool.name not in whitelist:
            continue
        description = TOOL_DESCRIPTIONS_OVERRIDE.get(tool.name, tool.description)
        # Deep-copy schema to avoid mutating the original
        parameters = _annotate_optionals(tool.inputSchema)
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
    return out


def _annotate_optionals(schema: dict[str, Any]) -> dict[str, Any]:
    """Prefix optional param descriptions with 'Optional. Omit if unknown.'

    DeepSeek / GLM-4.6 fail-fast doesn't tolerate ambiguous optional params;
    the prefix tells the model to omit rather than invent a default.
    """
    if not isinstance(schema, dict):
        return schema
    out = {k: v for k, v in schema.items()}
    properties = out.get("properties", {})
    required = set(out.get("required", []))
    new_props: dict[str, Any] = {}
    for name, prop in properties.items():
        prop_copy = {k: v for k, v in prop.items()} if isinstance(prop, dict) else prop
        if isinstance(prop_copy, dict) and name not in required:
            existing = prop_copy.get("description", "")
            if not existing.startswith("Optional. Omit if unknown."):
                if existing:
                    prop_copy["description"] = f"Optional. Omit if unknown. {existing}"
                else:
                    prop_copy["description"] = "Optional. Omit if unknown."
        new_props[name] = prop_copy
    out["properties"] = new_props
    return out
