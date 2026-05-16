"""Tests for AccountRepo CRUD + accounts/active_account schema."""

import os
import tempfile

import pytest
import pytest_asyncio

from deribit_trading.persistence import AccountRepo, Database


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
async def test_accounts_table_created(db):
    cursor = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
    )
    assert (await cursor.fetchone()) is not None


@pytest.mark.asyncio
async def test_active_account_table_created(db):
    cursor = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='active_account'"
    )
    assert (await cursor.fetchone()) is not None


@pytest.mark.asyncio
async def test_create_and_get(db):
    repo = AccountRepo(db)
    await repo.create(
        account_id="acc-1",
        alias="main",
        endpoint="deribit_testnet",
        client_id="client_x",
        client_secret_encrypted=b"\x00\x01encrypted",
        created_at=100,
    )
    got = await repo.get("acc-1")
    assert got["id"] == "acc-1"
    assert got["alias"] == "main"
    assert got["endpoint"] == "deribit_testnet"
    assert got["client_id"] == "client_x"
    assert got["client_secret"] == b"\x00\x01encrypted"
    assert got["last_used_at"] is None


@pytest.mark.asyncio
async def test_list_all_ordered(db):
    repo = AccountRepo(db)
    await repo.create("a1", "alpha", "deribit_prod", "x", b"e", 100)
    await repo.create("a2", "beta", "deribit_testnet", "y", b"e", 200)
    await repo.touch_last_used("a1", when_ms=500)
    rows = await repo.list_all()
    assert [r["id"] for r in rows] == ["a1", "a2"]


@pytest.mark.asyncio
async def test_get_by_alias(db):
    repo = AccountRepo(db)
    await repo.create("acc-x", "myalias", "deribit_testnet", "c", b"e", 100)
    found = await repo.get_by_alias("myalias")
    assert found is not None and found["id"] == "acc-x"
    missing = await repo.get_by_alias("nope")
    assert missing is None


@pytest.mark.asyncio
async def test_alias_unique_constraint(db):
    repo = AccountRepo(db)
    await repo.create("a1", "dup", "deribit_prod", "x", b"e", 100)
    import aiosqlite
    with pytest.raises(aiosqlite.IntegrityError):
        await repo.create("a2", "dup", "deribit_testnet", "y", b"e", 200)


@pytest.mark.asyncio
async def test_update_alias_and_secret(db):
    repo = AccountRepo(db)
    await repo.create("a1", "old", "deribit_prod", "x", b"old-secret", 100)
    ok = await repo.update("a1", alias="new", client_secret_encrypted=b"new-secret")
    assert ok is True
    got = await repo.get("a1")
    assert got["alias"] == "new"
    assert got["client_secret"] == b"new-secret"


@pytest.mark.asyncio
async def test_update_nothing_returns_false(db):
    repo = AccountRepo(db)
    await repo.create("a1", "x", "deribit_prod", "x", b"e", 100)
    ok = await repo.update("a1")
    assert ok is False


@pytest.mark.asyncio
async def test_delete(db):
    repo = AccountRepo(db)
    await repo.create("a1", "x", "deribit_prod", "x", b"e", 100)
    ok = await repo.delete("a1")
    assert ok is True
    assert await repo.get("a1") is None


@pytest.mark.asyncio
async def test_active_account_singleton(db):
    repo = AccountRepo(db)
    await repo.create("a1", "x", "deribit_prod", "x", b"e", 100)
    await repo.create("a2", "y", "deribit_testnet", "y", b"e", 100)

    assert await repo.get_active_id() is None
    await repo.set_active("a1")
    assert await repo.get_active_id() == "a1"
    await repo.set_active("a2")  # replaces, not duplicates
    assert await repo.get_active_id() == "a2"
    await repo.clear_active()
    assert await repo.get_active_id() is None


@pytest.mark.asyncio
async def test_touch_last_used(db):
    repo = AccountRepo(db)
    await repo.create("a1", "x", "deribit_prod", "x", b"e", 100)
    await repo.touch_last_used("a1", when_ms=999)
    got = await repo.get("a1")
    assert got["last_used_at"] == 999
