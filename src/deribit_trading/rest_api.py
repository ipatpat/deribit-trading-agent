"""FastAPI REST API for the trading system."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


class SmartOrderRequest(BaseModel):
    instrument_name: str
    direction: str
    amount: float
    algorithm: str = "tick-chaser"
    algo_params: dict = {}
    price_limit: float | None = None
    timeout_ms: int | None = 120_000
    prefer_maker: bool = True
    patience: float = 0.5


class SmartOrderActionRequest(BaseModel):
    action: str  # pause, resume, cancel, market


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
        return [p.model_dump() for p in positions]

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

        # Enrich positions with leverage
        all_positions = [p.model_dump() for p in btc_pos] + [p.model_dump() for p in eth_pos]

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
        config = SmartOrderConfig(
            instrument_name=req.instrument_name,
            direction=req.direction,
            amount=req.amount,
            algorithm=req.algorithm,
            algo_params=req.algo_params,
            price_limit=req.price_limit,
            timeout_ms=req.timeout_ms,
            prefer_maker=req.prefer_maker,
            patience=req.patience,
        )
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

    @app.post("/api/v1/settings/credentials")
    async def save_credentials(body: dict):
        client_id = body.get("client_id", "")
        client_secret = body.get("client_secret", "")
        env = body.get("env", env_manager.current_env)
        endpoint = body.get("endpoint")
        if not client_id or not client_secret:
            raise HTTPException(400, "client_id and client_secret required")

        # Check if client_id changed → clear private data
        data_cleared = False
        if container and container.key_store:
            from .config import Environment
            existing_key = container.key_store.get_key(Environment(env), "main")
            if existing_key and existing_key.client_id != client_id:
                deleted = await container.db.clear_private_data(env)
                data_cleared = True
                logger.info("Client ID changed for env=%s, cleared %d rows", env, deleted)

        # Set production endpoint if provided
        if endpoint and env == "production":
            env_manager.set_production_endpoint(endpoint)

        # Save to KeyStore
        if container and container.key_store:
            from .config import Environment
            container.key_store.add_key(
                env=Environment(env), name="main",
                client_id=client_id, client_secret=client_secret,
                scopes="account:read,trade:read_write",
            )

        # Reconnect
        try:
            result = await container.reconnect(env, client_id, client_secret)
            return {**result, "client_id": client_id, "data_cleared": data_cleared}
        except Exception as e:
            raise HTTPException(500, f"Reconnect failed: {e}")

    @app.post("/api/v1/settings/switch-env")
    async def switch_env(body: dict):
        env = body.get("env", "")
        if env not in ("testnet", "production"):
            raise HTTPException(400, "env must be 'testnet' or 'production'")

        # Try to find credentials for this env
        if container and container.key_store:
            from .config import Environment
            key = container.key_store.get_key(Environment(env), "main")
            if key:
                result = await container.reconnect(env, key.client_id, key.client_secret)
                return result
            else:
                raise HTTPException(400, f"No credentials stored for {env}")
        raise HTTPException(503, "KeyStore not available")

    @app.post("/api/v1/settings/clear-keys")
    async def clear_keys(body: dict[str, Any]) -> dict[str, Any]:
        env_str = body.get("env", env_manager.current_env)
        if container and container.key_store:
            from .config import Environment
            container.key_store.remove_key(Environment(env_str), "main")
        # Clear private data too
        deleted = 0
        if container:
            deleted = await container.db.clear_private_data(env_str)
        # Disconnect if current env
        if env_str == env_manager.current_env and container:
            await container.client.disconnect()
        return {"status": "cleared", "env": env_str, "data_rows_deleted": deleted}

    @app.post("/api/v1/settings/clear-account-data")
    async def clear_account_data(body: dict[str, Any]) -> dict[str, Any]:
        env_str = body.get("env", env_manager.current_env)
        if not container:
            raise HTTPException(503, "Not available")
        deleted = await container.db.clear_private_data(env_str)
        return {"status": "cleared", "env": env_str, "rows_deleted": deleted}

    return app
