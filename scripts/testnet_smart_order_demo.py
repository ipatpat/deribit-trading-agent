"""One-shot testnet demo: place a Standard intent SmartOrder and clean up.

Goal: end-to-end smoke test of the new intent-driven SmartOrder flow against
test.deribit.com without bringing up the full long-running API process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from deribit_trading.client import DeribitClient
from deribit_trading.config import Environment, KeyStore
import deribit_trading.algorithms.intent_router  # noqa: F401
import deribit_trading.algorithms.legacy  # noqa: F401
from deribit_trading.smart_order.engine import SmartOrderEngine
from deribit_trading.smart_order.types import SmartOrderConfig, SmartOrderState

TESTNET_URL = "wss://test.deribit.com/ws/api/v2"
KEYS_DB = "/Users/Pat/Python_material/deribit/data/keys.db"
MASTER_PW = os.getenv("DERIBIT_MASTER_PASSWORD", "deribit-local")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("demo")


async def main() -> int:
    ks = KeyStore(KEYS_DB, MASTER_PW)
    keys = ks.list_keys(Environment.TESTNET)
    if not keys:
        log.error("No testnet keys found in %s", KEYS_DB)
        return 1
    key = ks.get_key(Environment.TESTNET, keys[0].name)
    log.info("Using testnet key client_id=%s", key.client_id)

    client = DeribitClient(TESTNET_URL)
    await client.connect()
    await client.authenticate(key.client_id, key.client_secret)
    log.info("Authenticated")

    engine = SmartOrderEngine(client)
    await engine.start()

    so_id: str | None = None
    try:
        # Pull a fresh book quote so we can sanity-check the placed price
        book = await client.get_order_book("BTC-PERPETUAL", depth=1)
        log.info("BTC-PERPETUAL best_bid=%s best_ask=%s", book["bids"][0][0], book["asks"][0][0])

        cfg = SmartOrderConfig(
            instrument_name="BTC-PERPETUAL",
            direction="buy",
            amount=10,  # 10 USD — Deribit perp minimum
            intent="standard",
            t_patience_ms=15_000,
            max_cross_levels=1,
            price_limit_pct=0.005,
        )
        log.info("Creating SmartOrder: intent=standard amount=10 direction=buy")
        so = await engine.create_smart_order(cfg)
        so_id = so.id
        log.info(
            "Created so_id=%s state=%s level=%s price=%s deribit_order=%s",
            so.id, so.state, so.current_level, so.current_price, so.deribit_order_id,
        )

        # Watch for a few seconds so the engine processes some ticker updates
        for i in range(8):
            await asyncio.sleep(1)
            cur = engine.get_order(so.id)
            if cur is None:
                break
            log.info(
                "[t+%ds] state=%s level=%s price=%s filled=%s amend_count=%s reject_count=%s",
                i + 1, cur.state, cur.current_level, cur.current_price,
                cur.filled_amount, cur.amend_count, cur.post_only_reject_count,
            )
            if cur.state in (
                SmartOrderState.COMPLETED,
                SmartOrderState.MARKET_FILLED,
                SmartOrderState.CANCELLED,
                SmartOrderState.FAILED,
            ):
                log.info("Reached terminal state, stopping watch")
                break
    finally:
        if so_id:
            try:
                cancelled = await engine.cancel_smart_order(so_id)
                log.info("Cancel requested: state=%s", cancelled.state if cancelled else "n/a")
            except Exception as e:
                log.warning("Cancel failed (likely already terminal): %s", e)
        await engine.stop()
        await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
