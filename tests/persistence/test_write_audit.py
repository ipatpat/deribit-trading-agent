"""Tests for WriteAuditRepo + agent_write_audit schema migration."""

import os
import tempfile

import pytest
import pytest_asyncio

from deribit_trading.persistence import Database, WriteAuditRepo


@pytest_asyncio.fixture
async def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = Database(tmp.name)
    await database.open()
    yield database
    await database.close()
    os.unlink(tmp.name)


@pytest.mark.asyncio
async def test_schema_creates_audit_table(db):
    cursor = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_write_audit'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "agent_write_audit"


@pytest.mark.asyncio
async def test_audit_index_exists(db):
    cursor = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_audit_created_at'"
    )
    assert (await cursor.fetchone()) is not None


@pytest.mark.asyncio
async def test_record_inserts_and_fills_created_at(db):
    repo = WriteAuditRepo(db)
    await repo.record({
        "tool_call_id": "tc_test_1",
        "tool_name": "place_order",
        "args_json": '{"instrument_name":"BTC-PERPETUAL"}',
        "summary": "Place BTC perp",
        "decision": "confirmed",
        "env": "testnet",
    })
    rows = await repo.recent(limit=10)
    assert len(rows) == 1
    r = rows[0]
    assert r["tool_call_id"] == "tc_test_1"
    assert r["tool_name"] == "place_order"
    assert r["decision"] == "confirmed"
    assert r["env"] == "testnet"
    assert isinstance(r["created_at"], int) and r["created_at"] > 0


@pytest.mark.asyncio
async def test_record_all_three_decisions(db):
    repo = WriteAuditRepo(db)
    for i, decision in enumerate(("confirmed", "declined", "timeout"), start=1):
        await repo.record({
            "tool_call_id": f"tc_{i}",
            "tool_name": "cancel_order",
            "args_json": "{}",
            "summary": f"x {i}",
            "decision": decision,
            "env": "production",
        })
    rows = await repo.recent(limit=10)
    assert len(rows) == 3
    assert {r["decision"] for r in rows} == {"confirmed", "declined", "timeout"}


@pytest.mark.asyncio
async def test_decision_check_constraint(db):
    """CHECK constraint must reject invalid decisions."""
    import aiosqlite

    repo = WriteAuditRepo(db)
    with pytest.raises(aiosqlite.IntegrityError):
        await repo.record({
            "tool_call_id": "tc_bad",
            "tool_name": "place_order",
            "args_json": "{}",
            "summary": "x",
            "decision": "maybe",  # invalid
            "env": "testnet",
        })
