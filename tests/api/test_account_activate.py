"""Tests for the account-switch state machine.

We test the abstract `AccountManager.activate(...)` callback flow (which is
where the disconnect→reconnect orchestration lives, decoupled from the
WebSocket client) plus `clear_pending_confirmations()`. The end-to-end HTTP
activate endpoint is covered separately in test_accounts_endpoints.py.
"""

from __future__ import annotations

import asyncio

import pytest

from deribit_trading.agent.loop import (
    _pending_confirmations,
    clear_pending_confirmations,
)
from deribit_trading.config.account_manager import (
    Account,
    AccountManager,
    AccountSwitchError,
)


def _acc(id_: str, alias: str = "x", endpoint: str = "deribit_testnet") -> Account:
    return Account(
        id=id_,
        alias=alias,
        endpoint=endpoint,
        client_id="cid",
        created_at=1,
    )


# ── activate(): happy path ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_happy_path_runs_callbacks_in_order():
    mgr = AccountManager()
    target = _acc("acc-A", alias="A")
    order: list[str] = []

    async def reconnect_cb(acc, secret):
        order.append(f"reconnect:{acc.id}:{secret}")

    async def post_cb_1(acc):
        order.append(f"post1:{acc.id}")

    async def post_cb_2(acc):
        order.append(f"post2:{acc.id}")

    result = await mgr.activate(
        target, "shh", reconnect_cb, [post_cb_1, post_cb_2]
    )
    assert result is target
    assert mgr.active is target
    assert mgr.active_id == "acc-A"
    assert mgr.is_switching is False
    # reconnect runs before active is set + before post_reset_callbacks fire.
    assert order == ["reconnect:acc-A:shh", "post1:acc-A", "post2:acc-A"]


@pytest.mark.asyncio
async def test_activate_derives_env_label_from_endpoint():
    mgr = AccountManager()
    prod = _acc("p", endpoint="tibired_prod")
    test = _acc("t", endpoint="deribit_testnet")

    async def noop(*_a, **_k):
        return None

    await mgr.activate(prod, "s", noop)
    assert mgr.is_production() is True
    assert mgr.current_env == "production"
    assert mgr.ws_url.startswith("wss://www.tibired.com")

    await mgr.activate(test, "s", noop)
    assert mgr.is_production() is False
    assert mgr.current_env == "testnet"
    assert mgr.ws_url.startswith("wss://test.deribit.com")


# ── activate(): rollback on reconnect failure ───────────────────────


@pytest.mark.asyncio
async def test_activate_failure_keeps_previous_active():
    mgr = AccountManager()
    a = _acc("a", alias="A")
    b = _acc("b", alias="B")

    async def ok(_acc, _s):
        return None

    await mgr.activate(a, "s", ok)
    assert mgr.active_id == "a"

    async def boom(_acc, _s):
        raise RuntimeError("network down")

    with pytest.raises(AccountSwitchError) as ei:
        await mgr.activate(b, "s", boom)
    assert "network down" in str(ei.value)

    # Previous account remains active.
    assert mgr.active_id == "a"
    assert mgr.is_switching is False


@pytest.mark.asyncio
async def test_activate_failure_skips_post_callbacks():
    """If reconnect fails, post-reset callbacks must not fire — otherwise
    downstream listeners think the switch succeeded."""
    mgr = AccountManager()
    target = _acc("t")
    called: list[str] = []

    async def fail_cb(_acc, _s):
        raise RuntimeError("auth bad")

    async def post_cb(_acc):
        called.append("post")

    with pytest.raises(AccountSwitchError):
        await mgr.activate(target, "s", fail_cb, [post_cb])
    assert called == []
    assert mgr.active is None


@pytest.mark.asyncio
async def test_activate_swallows_post_callback_errors():
    """Post-reset listener failures must not abort the switch — the
    account is already authenticated at that point and rolling back
    would leave a dangling connection."""
    mgr = AccountManager()
    target = _acc("t")

    async def ok(_acc, _s):
        return None

    async def angry_post(_acc):
        raise RuntimeError("listener oops")

    result = await mgr.activate(target, "s", ok, [angry_post])
    assert result is target
    assert mgr.active_id == "t"  # still switched despite listener crash


# ── activate(): reentrancy guard ────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_rejects_overlap_in_progress():
    """A second activate() while one is in flight must fail fast rather
    than queue — otherwise a user double-clicking the UI ends up on an
    unexpected account."""
    mgr = AccountManager()
    a = _acc("a")
    b = _acc("b")
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_acc, _s):
        started.set()
        await release.wait()

    task = asyncio.create_task(mgr.activate(a, "s", slow))
    await started.wait()
    with pytest.raises(AccountSwitchError, match="in progress"):
        await mgr.activate(b, "s", lambda *_: None)

    release.set()
    await task
    assert mgr.active_id == "a"


# ── clear_pending_confirmations ─────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_pending():
    _pending_confirmations.clear()
    yield
    _pending_confirmations.clear()


@pytest.mark.asyncio
async def test_clear_pending_confirmations_empty():
    assert clear_pending_confirmations(reason="account_switched") == 0


@pytest.mark.asyncio
async def test_clear_pending_confirmations_fails_all_open_futures():
    f1: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    f2: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    f3: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
    f3.set_result(True)  # already done — must be left alone but evicted
    _pending_confirmations["t1"] = f1
    _pending_confirmations["t2"] = f2
    _pending_confirmations["t3"] = f3

    cleared = clear_pending_confirmations(reason="account_switched")
    assert cleared == 2  # f3 was already resolved
    assert f1.done() and f1.result() is False
    assert f2.done() and f2.result() is False
    assert f3.result() is True  # untouched
    assert _pending_confirmations == {}  # all evicted regardless of state
