"""Tests for engine action dispatch and escalation state transitions.

Uses an in-process fake DeribitClient. The IntentRouter algorithm itself is
covered by test_intent_router.py; here we verify the engine correctly
dispatches each Action variant and tracks current_level / state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

import deribit_trading.algorithms.intent_router  # noqa: F401  # register
from deribit_trading.client.errors import DeribitAPIError
from deribit_trading.smart_order.engine import SmartOrderEngine
from deribit_trading.smart_order.types import (
    Action,
    SmartOrderConfig,
    SmartOrderState,
)


@dataclass
class _Order:
    order_id: str
    filled_amount: float = 0.0


class _Inst:
    def __init__(self, name: str, tick_size: float = 0.5) -> None:
        self.instrument_name = name
        self.tick_size = tick_size


class FakeClient:
    """In-process fake DeribitClient, records calls."""

    def __init__(self, ioc_filled: float = 1.0) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.next_order_id = 1
        self.ioc_filled = ioc_filled
        self.subscriptions: list[str] = []

    async def get_order_book(self, instrument: str, depth: int = 10) -> dict:
        return {
            "bids": [[100_000, 1], [99_999.5, 1]],
            "asks": [[100_001, 1], [100_001.5, 1]],
        }

    async def call(self, method: str, params: dict) -> dict:
        return {"mark_price": 100_000.5, "instrument_name": params.get("instrument_name", "")}

    async def get_instruments(self, currency: str) -> list:
        return [_Inst("BTC-PERPETUAL", tick_size=0.5)]

    async def subscribe(self, channels: list[str], callback) -> None:
        self.subscriptions.extend(channels)

    async def buy(self, instrument_name: str, amount: float, order_type: str, price: float | None = None,
                  post_only: bool = False, time_in_force: str | None = None) -> _Order:
        self.calls.append(("buy", {
            "instrument_name": instrument_name, "amount": amount,
            "order_type": order_type, "price": price, "post_only": post_only,
            "time_in_force": time_in_force,
        }))
        oid = f"ord-{self.next_order_id}"
        self.next_order_id += 1
        if time_in_force == "immediate_or_cancel":
            return _Order(order_id=oid, filled_amount=self.ioc_filled)
        return _Order(order_id=oid)

    async def sell(self, *args, **kwargs) -> _Order:
        return await self.buy(*args, **kwargs)

    async def edit(self, order_id: str, amount: float, price: float, post_only: bool = True) -> _Order:
        self.calls.append(("edit", {
            "order_id": order_id, "amount": amount, "price": price, "post_only": post_only,
        }))
        oid = f"ord-{self.next_order_id}"
        self.next_order_id += 1
        return _Order(order_id=oid)

    async def cancel(self, order_id: str) -> None:
        self.calls.append(("cancel", {"order_id": order_id}))


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_standard_initial_place_uses_post_only_true() -> None:
    fake = FakeClient()
    engine = SmartOrderEngine(fake)  # type: ignore[arg-type]
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="standard",
    )
    so = await engine.create_smart_order(cfg)
    # First buy call must be a limit with post_only=True at best_bid (100_000)
    buy_calls = [c for c in fake.calls if c[0] == "buy"]
    assert len(buy_calls) == 1
    args = buy_calls[0][1]
    assert args["order_type"] == "limit"
    assert args["post_only"] is True
    assert args["price"] == 100_000
    assert so.current_level == 0
    assert so.state == SmartOrderState.ACTIVE


@pytest.mark.asyncio
async def test_urgent_initial_fires_ioc_then_market_for_residual() -> None:
    fake = FakeClient(ioc_filled=0.6)  # IOC fills only 0.6 of 1.0
    engine = SmartOrderEngine(fake)  # type: ignore[arg-type]
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="urgent", max_cross_levels=1,
    )
    so = await engine.create_smart_order(cfg)

    buy_calls = [c for c in fake.calls if c[0] == "buy"]
    # Expect: 1 IOC + 1 market for residual 0.4
    assert len(buy_calls) == 2
    assert buy_calls[0][1]["time_in_force"] == "immediate_or_cancel"
    assert buy_calls[0][1]["post_only"] is False
    assert buy_calls[1][1]["order_type"] == "market"
    assert abs(buy_calls[1][1]["amount"] - 0.4) < 1e-6
    assert so.state == SmartOrderState.MARKET_FILLED
    assert so.current_level == 4


@pytest.mark.asyncio
async def test_urgent_full_fill_completes() -> None:
    fake = FakeClient(ioc_filled=1.0)  # IOC fully fills
    engine = SmartOrderEngine(fake)  # type: ignore[arg-type]
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="urgent",
    )
    so = await engine.create_smart_order(cfg)
    assert so.state == SmartOrderState.COMPLETED
    assert so.filled_amount == 1.0


@pytest.mark.asyncio
async def test_terminal_state_emits_structured_log(caplog) -> None:
    """Group 10.1: terminal SmartOrder must emit one structured log line."""
    import logging
    fake = FakeClient(ioc_filled=1.0)
    engine = SmartOrderEngine(fake)  # type: ignore[arg-type]
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1, intent="urgent",
    )
    with caplog.at_level(logging.INFO, logger="deribit_trading.smart_order.engine"):
        await engine.create_smart_order(cfg)
    terminal_lines = [r for r in caplog.records if "smart_order_terminal" in r.message]
    assert len(terminal_lines) == 1
    msg = terminal_lines[0].message
    for tok in ("intent=", "current_level=", "elapsed_ms=", "fill_ratio=", "maker_ratio="):
        assert tok in msg


@pytest.mark.asyncio
async def test_post_only_reject_on_initial_triggers_recovery() -> None:
    fake = FakeClient()
    # Make the first buy raise 10041
    original_buy = fake.buy
    call_count = [0]

    async def buy_with_first_reject(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise DeribitAPIError(10041, "post_only_reject")
        return await original_buy(*args, **kwargs)

    fake.buy = buy_with_first_reject  # type: ignore[assignment]

    engine = SmartOrderEngine(fake)  # type: ignore[arg-type]
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="standard",
    )
    so = await engine.create_smart_order(cfg)
    # Recovery path triggered: post_only_reject_count > 0
    assert so.post_only_reject_count >= 1
    # Final state should NOT be FAILED (the spec requires recovery, not termination)
    assert so.state != SmartOrderState.FAILED


@pytest.mark.asyncio
async def test_action_dispatch_amend_passes_post_only() -> None:
    """Verify amend Action with post_only flag is propagated to client.edit."""
    fake = FakeClient()
    engine = SmartOrderEngine(fake)  # type: ignore[arg-type]
    cfg = SmartOrderConfig(
        instrument_name="BTC-PERPETUAL", direction="buy", amount=1,
        intent="standard",
    )
    so = await engine.create_smart_order(cfg)
    so.current_price = 100_000

    # Manually dispatch an amend action with post_only=False (mimicking Lv2 transition)
    engine._handle_action(so, Action.amend(100_001, post_only=False))
    # Throttle is async; wait briefly for it to drain
    await engine.start()
    await asyncio.sleep(0.5)
    await engine.stop()

    edit_calls = [c for c in fake.calls if c[0] == "edit"]
    assert len(edit_calls) >= 1
    assert edit_calls[-1][1]["post_only"] is False
    assert edit_calls[-1][1]["price"] == 100_001
