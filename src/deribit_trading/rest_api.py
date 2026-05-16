"""FastAPI REST API for the trading system."""

import asyncio
import json
import logging
import time
import warnings
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from .config import EnvManager
from .models import OrderType
from .persistence.repositories import MarketCandleRepo
from .services import MarketDataService, PortfolioService, TradingService
from .services.risk_manager import RiskManager
from .smart_order.engine import SmartOrderEngine
from .smart_order.types import SmartOrderConfig


# ── Request/Response schemas ────────────────────────────────────────

class OrderRequest(BaseModel):
    instrument_name: str
    direction: str  # "buy" or "sell"
    amount: float
    order_type: str = "limit"
    price: float | None = None
    label: str | None = None


_OVERRIDE_KEYS = {
    "t_patience_ms",
    "max_cross_levels",
    "price_limit_pct",
    "price_limit_ticks",
    "price_limit_iv",
    "prefer_maker",
}


class SmartOrderRequest(BaseModel):
    """Create-SmartOrder request body.

    Intent path (preferred): pass `intent` ("standard" | "urgent") with optional
    `overrides` dict tuning t_patience_ms / max_cross_levels / price_limit_*.

    Legacy path (deprecated, kept 1 minor version): pass `algorithm` +
    `algo_params`, or `patience` for the old TickChaser/TimedEscalation flow.
    """

    instrument_name: str
    direction: str
    amount: float

    # Intent path
    intent: Literal["standard", "urgent"] | None = None
    overrides: dict[str, Any] | None = None

    # Legacy path (deprecated)
    algorithm: str | None = None
    algo_params: dict = Field(default_factory=dict)
    patience: float | None = None
    price_limit: float | None = None
    timeout_ms: int | None = None
    prefer_maker: bool = True


def _build_smart_order_config(req: SmartOrderRequest) -> SmartOrderConfig:
    """Translate request into SmartOrderConfig, handling intent + legacy paths."""
    # Legacy path: explicit algorithm name takes precedence (kept for 1 minor version)
    if req.algorithm is not None:
        warnings.warn(
            "POST /api/v1/smart-orders: 'algorithm' field is deprecated; "
            "use 'intent' (standard|urgent) with optional 'overrides'.",
            DeprecationWarning,
            stacklevel=2,
        )
        return SmartOrderConfig(
            instrument_name=req.instrument_name,
            direction=req.direction,
            amount=req.amount,
            algorithm=req.algorithm,
            algo_params=req.algo_params,
            price_limit=req.price_limit,
            timeout_ms=req.timeout_ms,
            prefer_maker=req.prefer_maker,
        )

    # Legacy path: only `patience` provided → from_legacy adapter (also deprecated)
    if req.intent is None and req.patience is not None:
        return SmartOrderConfig.from_legacy(
            instrument_name=req.instrument_name,
            direction=req.direction,
            amount=req.amount,
            patience=req.patience,
            prefer_maker=req.prefer_maker,
        )

    # Intent path
    intent = req.intent or "standard"
    overrides = req.overrides or {}
    unknown = set(overrides) - _OVERRIDE_KEYS
    if unknown:
        raise HTTPException(
            400, f"Unknown overrides keys: {sorted(unknown)}. Allowed: {sorted(_OVERRIDE_KEYS)}"
        )
    return SmartOrderConfig(
        instrument_name=req.instrument_name,
        direction=req.direction,
        amount=req.amount,
        intent=intent,
        **overrides,
    )


class SmartOrderActionRequest(BaseModel):
    action: str  # pause, resume, cancel, market


def _id_tail(client_id: str) -> str:
    """Last 4 chars of client_id, or the whole thing if shorter."""
    return client_id[-4:] if len(client_id) >= 4 else client_id


async def _probe_credentials(ws_url: str, client_id: str, client_secret: str) -> dict[str, Any]:
    """Connect, authenticate, disconnect. Returns ok/auth_failed/connect_failed.

    Used by the two test-credentials endpoints. Reuses DeribitClient so we
    exercise the same code path as production.
    """
    from .client import DeribitClient
    probe = DeribitClient(ws_url)
    try:
        await probe.connect()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "connect", "error": str(e)}
    try:
        await probe.authenticate(client_id, client_secret)
        return {"ok": True, "ws_url": ws_url}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "authenticate", "error": str(e)}
    finally:
        try:
            await probe.disconnect()
        except Exception:  # noqa: BLE001
            pass


class HealthResponse(BaseModel):
    status: str
    env: str
    is_production: bool
    allow_live_trading: bool
    ws_url: str


# ── App factory ─────────────────────────────────────────────────────

def create_rest_app(
    market_data: MarketDataService,
    trading: TradingService,
    portfolio: PortfolioService,
    env_manager: EnvManager,
    smart_engine: SmartOrderEngine | None = None,
    risk_manager: RiskManager | None = None,
    candle_repo: MarketCandleRepo | None = None,
    container=None,
) -> FastAPI:
    """Create the FastAPI application with all routes."""

    app = FastAPI(
        title="Deribit Trading System",
        version="0.1.0",
        docs_url="/docs",
    )

    # ── CORS ────────────────────────────────────────────────────────

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── WebSocket for frontend live data ────────────────────────────

    ws_clients: set[WebSocket] = set()

    async def broadcast(msg_type: str, data: Any) -> None:
        """Broadcast a message to all connected frontend WebSocket clients."""
        if not ws_clients:
            return
        message = json.dumps({"type": msg_type, "data": data}, default=str)
        disconnected: list[WebSocket] = []
        for ws in ws_clients:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            ws_clients.discard(ws)

    # Expose broadcast so __main__.py can wire it to event sources
    app.state.broadcast = broadcast
    app.state.ws_clients = ws_clients

    @app.websocket("/ws/live")
    async def websocket_live(ws: WebSocket) -> None:
        await ws.accept()
        ws_clients.add(ws)
        logger.info("Frontend WebSocket connected (%d clients)", len(ws_clients))
        try:
            while True:
                # Keep alive — just wait for client messages (ping/pong handled by framework)
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ws_clients.discard(ws)
            logger.info("Frontend WebSocket disconnected (%d clients)", len(ws_clients))

    # ── Equity curve ────────────────────────────────────────────────

    @app.get("/api/v1/equity-curve")
    async def get_equity_curve(
        currency: str = Query("BTC"),
        since: int | None = Query(None, description="Start timestamp (ms)"),
        until: int | None = Query(None, description="End timestamp (ms)"),
        max_points: int = Query(1000, ge=10, le=10000),
    ) -> dict[str, Any]:
        now = int(time.time() * 1000)
        _since = since or (now - 86_400_000)  # default 1 day
        _until = until or now
        return await portfolio.get_equity_curve(currency, _since, _until, max_points)

    # ── Options (uses get_book_summary_by_currency for speed) ──────

    import math

    def _bs_delta(S: float, K: float, T: float, sigma: float, opt_type: str) -> float | None:
        """Black-Scholes delta approximation. T in years, sigma as decimal (e.g. 0.5)."""
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return None
        try:
            d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
            nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
            return nd1 if opt_type == "C" else nd1 - 1
        except (ValueError, ZeroDivisionError):
            return None

    async def _get_option_summaries(currency: str) -> list[dict[str, Any]]:
        """Fetch ALL option data in a single API call (~500ms for 1000+ options)."""
        result = await trading._client.call(
            "public/get_book_summary_by_currency",
            {"currency": currency, "kind": "option"},
        )
        return result

    def _parse_option_name(name: str) -> dict[str, str] | None:
        """Parse BTC-29MAY26-84000-C → {currency, expiry, strike, type}."""
        parts = name.split("-")
        if len(parts) == 4:
            return {"currency": parts[0], "expiry": parts[1], "strike": parts[2], "type": parts[3]}
        return None

    @app.get("/api/v1/options/expiries")
    async def get_option_expiries(currency: str = Query("BTC")) -> list[dict[str, Any]]:
        summaries = await _get_option_summaries(currency)

        # Get underlying price for ATM calculation
        underlying = 0.0
        for s in summaries:
            up = s.get("underlying_price")
            if up and up > 0:
                underlying = up
                break

        # Group by expiry, find ATM IV per expiry
        by_expiry: dict[str, list[dict]] = {}
        for s in summaries:
            parsed = _parse_option_name(s.get("instrument_name", ""))
            if parsed:
                exp = parsed["expiry"]
                if exp not in by_expiry:
                    by_expiry[exp] = []
                by_expiry[exp].append({**s, **parsed})

        # Get expiry timestamps
        instruments = await market_data.get_instruments(currency, kind="option")
        expiry_ts: dict[str, int] = {}
        for inst in instruments:
            parts = inst.instrument_name.split("-")
            if len(parts) == 4 and inst.expiration_timestamp:
                expiry_ts[parts[1]] = inst.expiration_timestamp

        now = int(time.time() * 1000)
        expiries = []
        for exp_str in sorted(by_expiry.keys(), key=lambda e: expiry_ts.get(e, 0)):
            ts = expiry_ts.get(exp_str, 0)
            if ts <= now:
                continue
            days = (ts - now) // 86_400_000

            # Find ATM IV: call closest to underlying price
            options = by_expiry[exp_str]
            atm_iv = 0.0
            best_dist = float("inf")
            for opt in options:
                strike = float(opt.get("strike", 0))
                iv = opt.get("mark_iv", 0) or 0
                if opt.get("type") == "C" and iv > 0:
                    dist = abs(strike - underlying)
                    if dist < best_dist:
                        best_dist = dist
                        atm_iv = iv

            expiries.append({
                "timestamp": ts,
                "expiry": exp_str,
                "days_to_expiry": days,
                "atm_iv": round(atm_iv, 2),
            })
        return expiries

    @app.get("/api/v1/options/chain")
    async def get_option_chain_endpoint(
        currency: str = Query("BTC"),
        expiry: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        summaries = await _get_option_summaries(currency)

        # Filter by expiry if specified
        if expiry:
            exp_upper = expiry.upper()
            summaries = [s for s in summaries if exp_upper in s.get("instrument_name", "").upper()]

        # Get expiry timestamps for T (time to expiry) calculation
        instruments = await market_data.get_instruments(currency, kind="option")
        expiry_ts_map: dict[str, int] = {}
        for inst in instruments:
            parts = inst.instrument_name.split("-")
            if len(parts) == 4 and inst.expiration_timestamp:
                expiry_ts_map[parts[1]] = inst.expiration_timestamp

        now_ms = int(time.time() * 1000)

        # Group by strike
        strikes: dict[float, dict[str, Any]] = {}
        for s in summaries:
            parsed = _parse_option_name(s.get("instrument_name", ""))
            if not parsed:
                continue
            strike = float(parsed["strike"])
            if strike not in strikes:
                strikes[strike] = {"strike": strike, "call": None, "put": None}

            # Calculate delta from BS model
            underlying = s.get("underlying_price") or 0
            iv_pct = s.get("mark_iv") or 0
            exp_ts = expiry_ts_map.get(parsed["expiry"], 0)
            T_years = max((exp_ts - now_ms) / (365.25 * 24 * 3600 * 1000), 1e-6) if exp_ts > now_ms else 1e-6
            delta = _bs_delta(underlying, strike, T_years, iv_pct / 100, parsed["type"])

            data = {
                "instrument_name": s.get("instrument_name"),
                "mark_price": s.get("mark_price"),
                "best_bid_price": s.get("bid_price"),
                "best_ask_price": s.get("ask_price"),
                "implied_volatility": s.get("mark_iv"),
                "volume_24h": s.get("volume"),
                "open_interest": s.get("open_interest"),
                "last_price": s.get("last"),
                "mid_price": s.get("mid_price"),
                "underlying_price": s.get("underlying_price"),
                "delta": round(delta, 4) if delta is not None else None,
            }

            if parsed["type"] == "C":
                strikes[strike]["call"] = data
            else:
                strikes[strike]["put"] = data

        return sorted(strikes.values(), key=lambda x: x["strike"])

    @app.get("/api/v1/options/vol-surface")
    async def get_vol_surface_endpoint(currency: str = Query("BTC")) -> dict[str, Any]:
        summaries = await _get_option_summaries(currency)

        # Group by expiry → {strike: IV}
        surface: dict[str, dict[str, float]] = {}
        for s in summaries:
            parsed = _parse_option_name(s.get("instrument_name", ""))
            iv = s.get("mark_iv")
            if not parsed or iv is None:
                continue
            exp = parsed["expiry"]
            strike = parsed["strike"]
            if exp not in surface:
                surface[exp] = {}
            surface[exp][strike] = iv

        return surface

    @app.get("/api/v1/options/ticker")
    async def get_option_ticker(instrument: str = Query(...)) -> dict[str, Any]:
        """Get full ticker with Greeks for a single option (on-demand)."""
        ticker = await market_data.get_ticker(instrument)
        return ticker.model_dump()

    # ── Option Payoff ──────────────────────────────────────────────

    @app.post("/api/v1/options/payoff")
    async def calculate_payoff(body: dict[str, Any]) -> dict[str, Any]:
        """Calculate multi-leg option payoff curve."""
        legs_input = body.get("legs", [])
        if not legs_input:
            raise HTTPException(400, "legs required")

        price_range = body.get("price_range")
        points = body.get("points", 100)

        # Fetch ticker for each leg in parallel
        async def fetch_leg_info(leg: dict) -> dict:
            instrument = leg["instrument"]
            direction = leg.get("direction", "buy")
            amount = leg.get("amount", 1)
            direction_mult = 1 if direction == "buy" else -1

            # Identify instrument type by name segments
            parts = instrument.split("-")
            if len(parts) == 4 and parts[3] in ("C", "P"):
                # Option: BTC-27JUN25-70000-C
                inst_type = "call" if parts[3] == "C" else "put"
                strike = float(parts[2])
            elif len(parts) == 2:
                # Future: BTC-PERPETUAL or BTC-27JUN25
                inst_type = "future"
                strike = 0.0
            elif len(parts) == 3 and parts[2] in ("C", "P"):
                # Edge case: malformed option without expiry — reject
                raise HTTPException(400, f"Invalid instrument: {instrument}")
            else:
                raise HTTPException(400, f"Invalid instrument: {instrument}")

            # Get market price
            try:
                ticker = await trading._client.call("public/ticker", {"instrument_name": instrument})
                mark = ticker.get("mark_price", 0)
                underlying = ticker.get("underlying_price", 0) or mark
            except Exception:
                raise HTTPException(400, f"Cannot fetch ticker for {instrument}")

            if inst_type == "future":
                entry_price = mark
                return {
                    "instrument": instrument,
                    "direction": direction,
                    "amount": amount,
                    "strike": 0,
                    "type": "future",
                    "entry_price": entry_price,
                    "premium_btc": 0,
                    "premium_usd": 0,
                    "delta": direction_mult * amount,
                    "theta": 0,
                    "underlying_price": underlying,
                }
            else:
                bid = ticker.get("best_bid_price") or mark
                ask = ticker.get("best_ask_price") or mark
                delta = (ticker.get("greeks") or {}).get("delta", 0)
                theta = (ticker.get("greeks") or {}).get("theta", 0)

                # Premium: buy uses ask, sell uses bid
                premium = ask if direction == "buy" else bid
                if not premium or premium <= 0:
                    premium = mark

                return {
                    "instrument": instrument,
                    "direction": direction,
                    "amount": amount,
                    "strike": strike,
                    "type": inst_type,
                    "premium_btc": premium,
                    "premium_usd": premium * underlying if underlying else 0,
                    "delta": delta * direction_mult * amount,
                    "theta": theta * direction_mult * amount,
                    "underlying_price": underlying,
                }

        import asyncio as _asyncio
        leg_infos = await _asyncio.gather(*[fetch_leg_info(l) for l in legs_input])

        # Determine price range
        underlying = leg_infos[0]["underlying_price"] if leg_infos else 0
        if not price_range:
            low = underlying * 0.7
            high = underlying * 1.3
        else:
            low, high = price_range[0], price_range[1]

        step = (high - low) / max(points - 1, 1)
        prices = [low + i * step for i in range(points)]

        # Calculate payoff at each price point
        payoff_btc = []
        payoff_usd = []
        for price in prices:
            total_pnl_btc = 0.0
            total_pnl_usd = 0.0
            for leg in leg_infos:
                direction_mult = 1 if leg["direction"] == "buy" else -1

                if leg["type"] == "future":
                    # Inverse contract (BTC/ETH): PnL in native currency
                    # Deribit inverse futures:
                    #   BTC-PERPETUAL: $10 per contract, PnL in BTC
                    #   ETH-PERPETUAL: $1 per contract, PnL in ETH
                    # Formula: PnL_coin = (1/entry - 1/price) * direction * amount
                    #          PnL_usd  = PnL_coin * price = (price/entry - 1) * direction * amount
                    entry = leg["entry_price"]
                    if entry > 0 and price > 0:
                        pnl_btc = (1.0 / entry - 1.0 / price) * direction_mult * leg["amount"]
                        pnl_usd = (price / entry - 1.0) * direction_mult * leg["amount"]
                    else:
                        pnl_btc = 0.0
                        pnl_usd = 0.0
                    total_pnl_btc += pnl_btc
                    total_pnl_usd += pnl_usd
                else:
                    # Option: call or put
                    if leg["type"] == "call":
                        intrinsic = max(0, price - leg["strike"])
                    else:
                        intrinsic = max(0, leg["strike"] - price)

                    leg_pnl = intrinsic - leg["premium_btc"]
                    total_pnl_btc += direction_mult * leg["amount"] * leg_pnl
                    total_pnl_usd += direction_mult * leg["amount"] * leg_pnl * underlying if underlying else 0

            payoff_btc.append({"price": round(price, 2), "pnl": round(total_pnl_btc, 8)})
            payoff_usd.append({"price": round(price, 2), "pnl": round(total_pnl_usd, 2)})

        # Summary
        pnls = [p["pnl"] for p in payoff_btc]
        max_profit = max(pnls)
        max_loss = min(pnls)

        # Find breakeven points (where PnL crosses zero)
        breakevens = []
        for i in range(1, len(pnls)):
            if (pnls[i-1] < 0 and pnls[i] >= 0) or (pnls[i-1] >= 0 and pnls[i] < 0):
                # Linear interpolation
                p1, p2 = payoff_btc[i-1]["price"], payoff_btc[i]["price"]
                v1, v2 = pnls[i-1], pnls[i]
                if v2 != v1:
                    be = p1 + (p2 - p1) * (-v1) / (v2 - v1)
                    breakevens.append(round(be, 2))

        net_premium = sum(
            (1 if l["direction"] == "buy" else -1) * l["amount"] * l.get("premium_btc", 0)
            for l in leg_infos
            if l["type"] != "future"
        )
        net_delta = sum(l["delta"] for l in leg_infos)
        net_theta = sum(l["theta"] for l in leg_infos)
        rr_ratio = abs(max_profit / max_loss) if max_loss != 0 else float('inf')

        return {
            "legs": leg_infos,
            "payoff_btc": payoff_btc,
            "payoff_usd": payoff_usd,
            "underlying_price": underlying,
            "summary": {
                "max_profit_btc": round(max_profit, 8),
                "max_loss_btc": round(max_loss, 8),
                "max_profit_usd": round(max_profit * underlying, 2) if underlying else 0,
                "max_loss_usd": round(max_loss * underlying, 2) if underlying else 0,
                "breakeven": breakevens,
                "net_premium_btc": round(net_premium, 8),
                "net_delta": round(net_delta, 4),
                "net_theta": round(net_theta, 4),
                "risk_reward_ratio": round(rr_ratio, 2),
            },
        }

    # ── Order Book ──────────────────────────────────────────────────

    @app.get("/api/v1/orderbook")
    async def get_orderbook(
        instrument: str = Query("BTC-PERPETUAL"),
        depth: int = Query(10, ge=1, le=50),
    ) -> dict[str, Any]:
        result = await market_data.get_orderbook(instrument, depth)
        return result

    # ── Positions ───────────────────────────────────────────────────

    @app.get("/api/v1/positions")
    async def get_positions(currency: str = Query("BTC")) -> list[dict[str, Any]]:
        positions = await trading.get_positions(currency)
        return [p.model_dump() for p in positions if p.size > 0]

    # ── Portfolio overview (multi-currency) ──────────────────────────

    @app.get("/api/v1/portfolio/overview")
    async def get_portfolio_overview() -> dict[str, Any]:
        """Multi-currency account overview: BTC + ETH + index prices + USD total."""
        # Use raw API call to get ALL fields (model_dump loses extra="ignore" fields)
        btc_raw, eth_raw, btc_pos, eth_pos, btc_idx, eth_idx = await asyncio.gather(
            trading._client.call("private/get_account_summary", {"currency": "BTC", "extended": True}, timeout=20),
            trading._client.call("private/get_account_summary", {"currency": "ETH", "extended": True}, timeout=20),
            trading._client.get_positions("BTC"),
            trading._client.get_positions("ETH"),
            trading._client.call("public/get_index_price", {"index_name": "btc_usd"}, timeout=20),
            trading._client.call("public/get_index_price", {"index_name": "eth_usd"}, timeout=20),
        )

        btc_price = btc_idx.get("index_price", 0)
        eth_price = eth_idx.get("index_price", 0)
        btc_equity = btc_raw.get("equity", 0)
        eth_equity = eth_raw.get("equity", 0)
        total_usd = btc_equity * btc_price + eth_equity * eth_price

        # Enrich positions with leverage; skip closed / net-zero positions
        all_positions = (
            [p.model_dump() for p in btc_pos if p.size > 0]
            + [p.model_dump() for p in eth_pos if p.size > 0]
        )

        return {
            "accounts": {
                "BTC": btc_raw,
                "ETH": eth_raw,
            },
            "positions": all_positions,
            "index_prices": {"BTC": btc_price, "ETH": eth_price},
            "total_usd": total_usd,
        }

    # ── Portfolio snapshot ──────────────────────────────────────────

    @app.get("/api/v1/portfolio/snapshot")
    async def get_portfolio_snapshot(currency: str = Query("BTC")) -> dict[str, Any]:
        snapshot = await portfolio.get_snapshot(currency)
        return snapshot.model_dump()

    # ── PnL attribution ─────────────────────────────────────────────

    @app.get("/api/v1/portfolio/pnl-attribution")
    async def get_pnl_attribution(currency: str = Query("BTC")) -> list[dict[str, Any]]:
        return await portfolio.get_pnl_attribution(currency)

    # ── Orders ──────────────────────────────────────────────────────

    @app.post("/api/v1/orders")
    async def create_order(req: OrderRequest) -> dict[str, Any]:
        try:
            order_type = OrderType(req.order_type)
            fn = trading.buy if req.direction == "buy" else trading.sell
            order = await fn(
                instrument_name=req.instrument_name,
                amount=req.amount,
                order_type=order_type,
                price=req.price,
                label=req.label,
            )
            return order.model_dump()
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/v1/orders/{order_id}")
    async def cancel_order(order_id: str) -> dict[str, Any]:
        order = await trading.cancel(order_id)
        return order.model_dump()

    @app.get("/api/v1/orders")
    async def get_orders(
        currency: str | None = Query(None),
        instrument_name: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        orders = await trading.get_open_orders(currency, instrument_name)
        return [o.model_dump() for o in orders]

    # ── Smart Orders ────────────────────────────────────────────────

    @app.post("/api/v1/smart-orders")
    async def create_smart_order(req: SmartOrderRequest) -> dict[str, Any]:
        if not smart_engine:
            raise HTTPException(503, "SmartOrderEngine not available")
        try:
            config = _build_smart_order_config(req)
        except ValueError as e:
            raise HTTPException(400, str(e))
        try:
            so = await smart_engine.create_smart_order(config)
            return so.to_dict()
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.get("/api/v1/smart-orders")
    async def list_smart_orders(active_only: bool = Query(True)) -> list[dict[str, Any]]:
        if not smart_engine:
            return []
        return [so.to_dict() for so in smart_engine.list_orders(active_only)]

    @app.get("/api/v1/smart-orders/{so_id}")
    async def get_smart_order(so_id: str) -> dict[str, Any]:
        if not smart_engine:
            raise HTTPException(503, "SmartOrderEngine not available")
        so = smart_engine.get_order(so_id)
        if not so:
            raise HTTPException(404, f"SmartOrder {so_id} not found")
        return so.to_dict()

    @app.delete("/api/v1/smart-orders/{so_id}")
    async def delete_smart_order(so_id: str) -> dict[str, Any]:
        if not smart_engine:
            raise HTTPException(503, "SmartOrderEngine not available")
        so = await smart_engine.cancel_smart_order(so_id)
        if not so:
            raise HTTPException(404, f"SmartOrder {so_id} not found")
        return so.to_dict()

    @app.post("/api/v1/smart-orders/{so_id}/actions")
    async def smart_order_action(so_id: str, req: SmartOrderActionRequest) -> dict[str, Any]:
        if not smart_engine:
            raise HTTPException(503, "SmartOrderEngine not available")
        if req.action == "pause":
            so = smart_engine.pause_smart_order(so_id)
        elif req.action == "resume":
            so = smart_engine.resume_smart_order(so_id)
        elif req.action == "cancel":
            so = await smart_engine.cancel_smart_order(so_id)
        elif req.action == "market":
            so = await smart_engine.market_smart_order(so_id)
        else:
            raise HTTPException(400, f"Unknown action: {req.action}")
        if not so:
            raise HTTPException(404, f"SmartOrder {so_id} not found")
        return so.to_dict()

    # ── Risk ───────────────────────────────────────────────────────

    @app.get("/api/v1/risk/status")
    async def get_risk_status() -> dict[str, Any]:
        if not risk_manager:
            return {"error": "RiskManager not available"}
        return risk_manager.get_risk_status()

    @app.put("/api/v1/risk/config")
    async def update_risk_config(config: dict[str, Any]) -> dict[str, Any]:
        if not risk_manager:
            raise HTTPException(503, "RiskManager not available")
        risk_manager.update_config(**config)
        return risk_manager.get_risk_status()

    @app.post("/api/v1/risk/resume")
    async def resume_trading() -> dict[str, Any]:
        if not risk_manager:
            raise HTTPException(503, "RiskManager not available")
        risk_manager.resume_trading()
        return {"status": "resumed"}

    # ── Candles ────────────────────────────────────────────────────

    # Map frontend resolution names to Deribit TradingView API resolution values
    _RES_TO_DERIBIT = {"1m": "1", "5m": "5", "1h": "60", "1d": "1D"}

    @app.get("/api/v1/candles")
    async def get_candles(
        instrument: str = Query("BTC-PERPETUAL"),
        resolution: str = Query("1m"),
        since: int | None = Query(None),
        until: int | None = Query(None),
    ) -> list[dict[str, Any]]:
        now = int(time.time() * 1000)
        _since = since or (now - 3_600_000)
        _until = until or now

        # Try local DB first
        if candle_repo:
            data = await candle_repo.get_candles(
                env_manager.current_env, instrument, resolution, _since, _until
            )
            if data:
                return data

        # Fallback: fetch from Deribit TradingView API directly
        deribit_res = _RES_TO_DERIBIT.get(resolution, resolution)
        try:
            result = await trading._client.call("public/get_tradingview_chart_data", {
                "instrument_name": instrument,
                "start_timestamp": _since,
                "end_timestamp": _until,
                "resolution": deribit_res,
            })
            ticks = result.get("ticks", [])
            opens = result.get("open", [])
            highs = result.get("high", [])
            lows = result.get("low", [])
            closes = result.get("close", [])
            volumes = result.get("volume", [])
            return [
                {
                    "timestamp": ticks[i],
                    "instrument_name": instrument,
                    "resolution": resolution,
                    "open": opens[i],
                    "high": highs[i],
                    "low": lows[i],
                    "close": closes[i],
                    "volume": volumes[i] if i < len(volumes) else 0,
                }
                for i in range(len(ticks))
            ]
        except Exception:
            return []

    # ── Health ──────────────────────────────────────────────────────

    @app.get("/api/v1/health")
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            env=env_manager.current_env,
            is_production=env_manager.is_production(),
            allow_live_trading=env_manager.allow_live_trading,
            ws_url=env_manager.ws_url,
        )

    # ── Settings ────────────────────────────────────────────────────

    @app.get("/api/v1/settings/status")
    async def get_settings_status():
        # Get client_id tail from KeyStore
        client_id_tail = ""
        has_credentials = False
        if container and container.key_store:
            from .config import Environment
            key = container.key_store.get_key(Environment(env_manager.current_env), "main")
            if key:
                has_credentials = True
                client_id_tail = key.client_id[-4:] if len(key.client_id) >= 4 else key.client_id

        return {
            "env": env_manager.current_env,
            "ws_url": env_manager.ws_url,
            "connected": container.client.is_connected if container else False,
            "authenticated": container.client.is_authenticated if container else False,
            "client_id": "",  # Don't expose
            "client_id_tail": client_id_tail,
            "has_credentials": has_credentials,
            "production_endpoint": env_manager.production_endpoint,
            "is_production": env_manager.is_production(),
            "allow_live_trading": env_manager.allow_live_trading,
            "uptime_ms": int((time.time() - container._start_time) * 1000) if container else 0,
        }

    # ── Accounts (multi-account management) ────────────────────────────

    @app.get("/api/v1/accounts")
    async def list_accounts() -> dict[str, Any]:
        if not container or not container.account_repo:
            raise HTTPException(503, "Account management unavailable")
        rows = await container.account_repo.list_all()
        active_id = await container.account_repo.get_active_id()
        from .config import ENDPOINTS

        def _row_dto(r: dict[str, Any]) -> dict[str, Any]:
            secret_tail = ""
            if container.key_store and r.get("client_secret"):
                try:
                    plain = container.key_store.decrypt(r["client_secret"])
                    secret_tail = _id_tail(plain)
                except Exception:  # noqa: BLE001
                    secret_tail = ""
            return {
                "id": r["id"],
                "alias": r["alias"],
                "endpoint": r["endpoint"],
                "client_id": "",  # never expose full id
                "client_id_tail": _id_tail(r["client_id"]),
                "client_secret_tail": secret_tail,
                "is_active": r["id"] == active_id,
                "endpoint_label": ENDPOINTS[r["endpoint"]].label
                if r["endpoint"] in ENDPOINTS else r["endpoint"],
                "is_production": ENDPOINTS[r["endpoint"]].is_production
                if r["endpoint"] in ENDPOINTS else False,
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
            }

        return {
            "accounts": [_row_dto(r) for r in rows],
            "active_id": active_id,
            "endpoints": [
                {"id": k, "label": v.label, "is_production": v.is_production}
                for k, v in ENDPOINTS.items()
            ],
        }

    @app.get("/api/v1/accounts/active")
    async def get_active_account() -> dict[str, Any]:
        if not container or not container.account_repo:
            raise HTTPException(503, "Account management unavailable")
        active_id = await container.account_repo.get_active_id()
        if not active_id:
            return {"active": None}
        row = await container.account_repo.get(active_id)
        if not row:
            return {"active": None}
        from .config import ENDPOINTS
        secret_tail = ""
        if container.key_store and row.get("client_secret"):
            try:
                secret_tail = _id_tail(container.key_store.decrypt(row["client_secret"]))
            except Exception:  # noqa: BLE001
                secret_tail = ""
        return {
            "active": {
                "id": row["id"],
                "alias": row["alias"],
                "endpoint": row["endpoint"],
                "endpoint_label": ENDPOINTS[row["endpoint"]].label
                if row["endpoint"] in ENDPOINTS else row["endpoint"],
                "is_production": ENDPOINTS[row["endpoint"]].is_production
                if row["endpoint"] in ENDPOINTS else False,
                "client_id_tail": _id_tail(row["client_id"]),
                "client_secret_tail": secret_tail,
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
            },
            "connected": container.client.is_connected,
            "authenticated": container.client.is_authenticated,
        }

    @app.post("/api/v1/accounts", status_code=201)
    async def create_account(body: dict[str, Any]) -> dict[str, Any]:
        if not container or not container.account_repo or not container.key_store:
            raise HTTPException(503, "Account management unavailable")
        alias = (body.get("alias") or "").strip()
        endpoint = (body.get("endpoint") or "").strip()
        client_id = (body.get("client_id") or "").strip()
        client_secret = body.get("client_secret") or ""
        if not alias:
            raise HTTPException(422, "alias is required")
        if not client_id or not client_secret:
            raise HTTPException(422, "client_id and client_secret are required")
        from .config import ENDPOINTS
        if endpoint not in ENDPOINTS:
            raise HTTPException(
                422, f"endpoint must be one of: {sorted(ENDPOINTS.keys())}"
            )
        # Alias uniqueness
        if await container.account_repo.get_by_alias(alias) is not None:
            raise HTTPException(422, f"alias '{alias}' already exists")

        import uuid
        new_id = str(uuid.uuid4())
        secret_blob = container.key_store.encrypt(client_secret)
        await container.account_repo.create(
            account_id=new_id,
            alias=alias,
            endpoint=endpoint,
            client_id=client_id,
            client_secret_encrypted=secret_blob,
            created_at=int(time.time() * 1000),
        )
        return {
            "id": new_id,
            "alias": alias,
            "endpoint": endpoint,
            "client_id_tail": _id_tail(client_id),
        }

    @app.put("/api/v1/accounts/{account_id}")
    async def update_account(account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if not container or not container.account_repo or not container.key_store:
            raise HTTPException(503, "Account management unavailable")
        existing = await container.account_repo.get(account_id)
        if not existing:
            raise HTTPException(404, f"Account {account_id} not found")

        new_alias = body.get("alias")
        new_secret = body.get("client_secret")
        if new_alias is not None:
            new_alias = new_alias.strip()
            if not new_alias:
                raise HTTPException(422, "alias cannot be empty")
            if new_alias != existing["alias"]:
                collision = await container.account_repo.get_by_alias(new_alias)
                if collision and collision["id"] != account_id:
                    raise HTTPException(422, f"alias '{new_alias}' already exists")

        secret_blob = (
            container.key_store.encrypt(new_secret) if new_secret else None
        )
        await container.account_repo.update(
            account_id,
            alias=new_alias,
            client_secret_encrypted=secret_blob,
        )
        return {"status": "updated", "id": account_id}

    @app.delete("/api/v1/accounts/{account_id}")
    async def delete_account(account_id: str) -> dict[str, Any]:
        if not container or not container.account_repo:
            raise HTTPException(503, "Account management unavailable")
        active_id = await container.account_repo.get_active_id()
        deleting_active = active_id == account_id

        # If deleting the active account, tear down the live connection +
        # engines first so we don't leave dangling state pointing at a
        # vanished account. Frontend boot path handles the "no active"
        # state via the onboarding banner.
        if deleting_active:
            await container.deactivate()

        # Drop per-account history before removing the row, so we don't leave
        # orphans pointing at a vanished account_id.
        await container.db.clear_private_data(account_id)
        ok = await container.account_repo.delete(account_id)
        if not ok:
            raise HTTPException(404, f"Account {account_id} not found")
        return {"status": "deleted", "id": account_id, "was_active": deleting_active}

    @app.post("/api/v1/accounts/{account_id}/activate")
    async def activate_account_endpoint(account_id: str) -> dict[str, Any]:
        if not container:
            raise HTTPException(503, "Container unavailable")
        try:
            result = await container.activate_account(account_id)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:  # noqa: BLE001
            logger.exception("activate_account failed")
            raise HTTPException(500, f"Activate failed: {e}")
        return result

    @app.post("/api/v1/accounts/test-credentials")
    async def test_credentials(body: dict[str, Any]) -> dict[str, Any]:
        endpoint = (body.get("endpoint") or "").strip()
        client_id = (body.get("client_id") or "").strip()
        client_secret = body.get("client_secret") or ""
        from .config import ENDPOINTS
        if endpoint not in ENDPOINTS:
            raise HTTPException(422, f"unknown endpoint '{endpoint}'")
        if not client_id or not client_secret:
            raise HTTPException(422, "client_id and client_secret are required")
        return await _probe_credentials(ENDPOINTS[endpoint].ws_url, client_id, client_secret)

    @app.post("/api/v1/accounts/{account_id}/test")
    async def test_existing_account(account_id: str) -> dict[str, Any]:
        if not container or not container.account_repo or not container.key_store:
            raise HTTPException(503, "Account management unavailable")
        row = await container.account_repo.get(account_id)
        if not row:
            raise HTTPException(404, f"Account {account_id} not found")
        from .config import ENDPOINTS
        if row["endpoint"] not in ENDPOINTS:
            raise HTTPException(500, f"Account references unknown endpoint {row['endpoint']}")
        ws_url = ENDPOINTS[row["endpoint"]].ws_url
        secret_plain = container.key_store.decrypt(row["client_secret"])
        return await _probe_credentials(ws_url, row["client_id"], secret_plain)

    # ── AI Agent: settings + test + chat ─────────────────────────────────
    @app.get("/api/v1/settings/ai-agent")
    async def get_ai_agent_settings() -> dict[str, Any]:
        """Return public AI agent config (no api_key)."""
        from .agent.llm_client import has_env_api_key
        if not container or not container.key_store:
            return {
                "endpoint": None, "model": None,
                "api_key_set": False, "env_fallback_available": has_env_api_key(),
            }
        cfg = container.key_store.get_ai_agent_public()
        cfg["env_fallback_available"] = has_env_api_key() if not cfg.get("api_key_set") else False
        return cfg

    @app.post("/api/v1/settings/ai-agent")
    async def set_ai_agent_settings(body: dict[str, Any]) -> dict[str, Any]:
        """Save AI agent config (encrypted)."""
        endpoint = body.get("endpoint", "").strip()
        model = body.get("model", "").strip()
        api_key = body.get("api_key", "").strip()
        if not (endpoint and model and api_key):
            raise HTTPException(400, "endpoint, model, and api_key are all required")
        if not container or not container.key_store:
            raise HTTPException(503, "KeyStore not available")
        container.key_store.set_ai_agent_config(endpoint, model, api_key)
        return {"ok": True, "api_key_set": True}

    @app.delete("/api/v1/settings/ai-agent")
    async def clear_ai_agent_settings() -> dict[str, Any]:
        """Clear AI agent config."""
        if not container or not container.key_store:
            raise HTTPException(503, "KeyStore not available")
        container.key_store.clear_ai_agent_config()
        return {"ok": True}

    @app.post("/api/v1/agent/test")
    async def test_ai_agent_connection(body: dict[str, Any]) -> dict[str, Any]:
        """Minimal 1-token chat completion to verify endpoint+model+key.

        If api_key is omitted (or blank) but a key is already saved in the
        keystore, fall back to it — lets the Settings UI test the saved key
        without forcing the user to re-type it.
        """
        from .agent.loop import test_connection as _test
        endpoint = body.get("endpoint", "").strip()
        model = body.get("model", "").strip()
        api_key = (body.get("api_key") or "").strip()
        if not api_key and container and container.key_store:
            saved = container.key_store.get_ai_agent_config()
            if saved:
                api_key = saved["api_key"]
                if not endpoint:
                    endpoint = saved["endpoint"]
                if not model:
                    model = saved["model"]
        if not (endpoint and model and api_key):
            raise HTTPException(400, "endpoint, model, and api_key are all required")
        return await _test(endpoint=endpoint, model=model, api_key=api_key)

    @app.post("/api/v1/agent/list-models")
    async def list_ai_agent_models(body: dict[str, Any]) -> dict[str, Any]:
        """Fetch the provider's available model list via OpenAI-compatible /v1/models.

        Same saved-key fallback as /agent/test.
        """
        from .agent.llm_client import list_models as _list
        endpoint = body.get("endpoint", "").strip()
        api_key = (body.get("api_key") or "").strip()
        if not api_key and container and container.key_store:
            saved = container.key_store.get_ai_agent_config()
            if saved:
                api_key = saved["api_key"]
                if not endpoint:
                    endpoint = saved["endpoint"]
        if not (endpoint and api_key):
            raise HTTPException(400, "endpoint and api_key are required")
        return await _list(endpoint=endpoint, api_key=api_key)

    @app.post("/api/v1/agent/chat")
    async def agent_chat_endpoint(request: Request) -> StreamingResponse:
        """Streaming SSE agent chat endpoint."""
        from .agent.llm_client import get_agent_config, make_client
        from .agent.loop import ToolDispatcher, agent_chat
        from .agent.system_prompt import build_system_prompt
        from .agent.tool_specs import convert_mcp_to_openai

        body = await request.json()
        user_messages = body.get("messages", [])
        page_context = body.get("page_context") or {}
        write_enabled = bool(body.get("write_enabled", False))

        if not container:
            raise HTTPException(503, "Backend not initialized")

        cfg = get_agent_config(container.key_store)
        if cfg is None or not cfg.is_configured:
            raise HTTPException(503, "AI agent not configured. Set endpoint/model/api_key in Settings.")

        # Build dispatcher backed by the in-process MCP server's call_tool.
        # We construct a fresh server here purely for tool dispatch routing.
        from .mcp_server import create_mcp_server
        mcp_server = create_mcp_server(
            market_data=container.market_data,
            trading=container.trading,
            portfolio=container.portfolio,
            env_manager=env_manager,
            smart_engine=container.smart_engine,
            candle_repo=candle_repo,
        )

        # Get the tool list from the MCP server (re-uses inputSchema definitions)
        # We invoke the registered list_tools handler.
        from mcp.types import ListToolsRequest
        tools_resp = await mcp_server.request_handlers[ListToolsRequest](
            ListToolsRequest(method="tools/list", params=None)
        )
        mcp_tools = tools_resp.root.tools
        openai_tools = convert_mcp_to_openai(mcp_tools, write_enabled=write_enabled)

        # The MCP server's call_tool handler is what we need to dispatch via.
        from mcp.types import CallToolRequest, CallToolRequestParams

        async def _mcp_call(name: str, arguments: dict) -> Any:
            req = CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name=name, arguments=arguments),
            )
            res = await mcp_server.request_handlers[CallToolRequest](req)
            return res.root.content

        dispatcher = ToolDispatcher(_mcp_call)
        client = make_client(cfg)
        system_prompt = build_system_prompt(page_context, write_enabled=write_enabled)
        audit_repo = None
        if container.db is not None:
            from .persistence import WriteAuditRepo
            audit_repo = WriteAuditRepo(container.db)

        async def _stream():
            try:
                async for ev in agent_chat(
                    client=client,
                    config=cfg,
                    system_prompt=system_prompt,
                    user_messages=user_messages,
                    tools=openai_tools,
                    dispatcher=dispatcher,
                    max_turns=15,
                    audit_repo=audit_repo,
                    account_id=(
                        await container.account_repo.get_active_id()
                        if container and container.account_repo
                        else "unknown"
                    ) or "unknown",
                    write_enabled=write_enabled,
                ):
                    yield ev.to_sse()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent chat error")
                from .agent.loop import SSEEvent
                yield SSEEvent("error", {"code": "internal", "message": str(exc)}).to_sse()
            finally:
                await client.close()

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx buffering
                "Connection": "keep-alive",
            },
        )

    class ConfirmBody(BaseModel):
        confirmed: bool
        reason: str | None = None

    @app.post("/api/v1/agent/confirm/{tool_call_id}")
    async def confirm_tool(tool_call_id: str, body: ConfirmBody) -> dict[str, Any]:
        """Resolve a paused agent write-tool call with the user's decision."""
        from .agent.loop import resolve_confirmation
        ok = resolve_confirmation(tool_call_id, body.confirmed)
        if not ok:
            raise HTTPException(404, "Unknown or already-resolved tool_call_id")
        return {"ok": True}

    return app
