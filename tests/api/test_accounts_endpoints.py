"""REST API tests for /api/v1/accounts endpoints.

We mount the FastAPI app with a stub ServiceContainer that wires a real
AccountRepo + real KeyStore + real Database (in tmp files) and stubs the
DeribitClient + activate_account method. The goal is to validate the HTTP
surface (status codes, payload shape, alias-UNIQUE, delete-active 409) —
the actual WebSocket switching flow is exercised in test_account_activate.
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from deribit_trading.config import EnvManager, Environment, KeyStore
from deribit_trading.persistence import AccountRepo, Database
from deribit_trading.rest_api import create_rest_app


@pytest_asyncio.fixture
async def harness():
    """Spin up a temp DB + temp keystore + minimal container + TestClient."""
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    keys_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    keys_file.close()

    db = Database(db_file.name)
    await db.open()
    key_store = KeyStore(keys_file.name, "test-master-pw")
    account_repo = AccountRepo(db)

    client_stub = SimpleNamespace(
        is_connected=False,
        is_authenticated=False,
    )

    # activate_account is awaited by the endpoint; provide a stub that just
    # records the call + flips the bool flags.
    activate_calls: list[str] = []

    async def fake_activate(account_id: str) -> dict:
        row = await account_repo.get(account_id)
        if not row:
            raise ValueError(f"Account {account_id} not found")
        activate_calls.append(account_id)
        client_stub.is_connected = True
        client_stub.is_authenticated = True
        await account_repo.set_active(account_id)
        return {
            "id": account_id,
            "alias": row["alias"],
            "endpoint": row["endpoint"],
            "client_id": row["client_id"],
            "connected": True,
            "authenticated": True,
        }

    deactivate_log: list[int] = []

    async def fake_deactivate() -> None:
        deactivate_log.append(1)
        client_stub.is_connected = False
        client_stub.is_authenticated = False
        await account_repo.clear_active()

    container = SimpleNamespace(
        client=client_stub,
        db=db,
        key_store=key_store,
        account_repo=account_repo,
        activate_account=fake_activate,
        deactivate=fake_deactivate,
        activate_calls=activate_calls,
        deactivate_log=deactivate_log,
        _start_time=0,
    )

    env_manager = EnvManager(initial_env=Environment.TESTNET)
    # market_data/trading/portfolio/etc unused by accounts endpoints; pass None.
    app = create_rest_app(
        market_data=None,
        trading=None,
        portfolio=None,
        env_manager=env_manager,
        container=container,
    )
    client = TestClient(app)
    yield SimpleNamespace(
        client=client,
        container=container,
        repo=account_repo,
        key_store=key_store,
    )

    await db.close()
    os.unlink(db_file.name)
    os.unlink(keys_file.name)


def _create(client: TestClient, **overrides) -> dict:
    body = {
        "alias": "main",
        "endpoint": "deribit_testnet",
        "client_id": "abc12345",
        "client_secret": "shh-secret",
    }
    body.update(overrides)
    resp = client.post("/api/v1/accounts", json=body)
    return resp


# ── List / active ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_empty(harness):
    resp = harness.client.get("/api/v1/accounts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["accounts"] == []
    assert body["active_id"] is None
    # Endpoint catalogue is always present so the UI can render the radio.
    ids = {e["id"] for e in body["endpoints"]}
    assert {"deribit_prod", "tibired_prod", "deribit_testnet"} <= ids


@pytest.mark.asyncio
async def test_get_active_when_none(harness):
    resp = harness.client.get("/api/v1/accounts/active")
    assert resp.status_code == 200
    assert resp.json()["active"] is None


# ── Create ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_happy_path(harness):
    resp = _create(harness.client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["alias"] == "main"
    assert body["endpoint"] == "deribit_testnet"
    assert body["client_id_tail"] == "2345"
    assert "id" in body

    # Round-trip via list.
    listed = harness.client.get("/api/v1/accounts").json()["accounts"]
    assert len(listed) == 1
    assert listed[0]["client_id"] == ""  # never exposed
    assert listed[0]["is_active"] is False


@pytest.mark.asyncio
async def test_create_rejects_missing_alias(harness):
    resp = _create(harness.client, alias="")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_unknown_endpoint(harness):
    resp = _create(harness.client, endpoint="nonsense")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_alias_422(harness):
    assert _create(harness.client, alias="dup").status_code == 201
    second = _create(harness.client, alias="dup", client_id="other")
    assert second.status_code == 422
    assert "already exists" in second.json()["detail"]


# ── Update ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_alias(harness):
    created = _create(harness.client).json()
    aid = created["id"]
    resp = harness.client.put(
        f"/api/v1/accounts/{aid}", json={"alias": "renamed"}
    )
    assert resp.status_code == 200
    listed = harness.client.get("/api/v1/accounts").json()["accounts"]
    assert listed[0]["alias"] == "renamed"


@pytest.mark.asyncio
async def test_update_alias_collision_422(harness):
    a = _create(harness.client, alias="a").json()
    _create(harness.client, alias="b", client_id="other")
    resp = harness.client.put(
        f"/api/v1/accounts/{a['id']}", json={"alias": "b"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_secret_re_encrypts(harness):
    created = _create(harness.client).json()
    aid = created["id"]
    before = await harness.repo.get(aid)
    resp = harness.client.put(
        f"/api/v1/accounts/{aid}", json={"client_secret": "rotated-secret"}
    )
    assert resp.status_code == 200
    after = await harness.repo.get(aid)
    assert after["client_secret"] != before["client_secret"]
    # Decrypting yields the rotated plaintext.
    assert harness.key_store.decrypt(after["client_secret"]) == "rotated-secret"


@pytest.mark.asyncio
async def test_update_unknown_404(harness):
    resp = harness.client.put(
        "/api/v1/accounts/does-not-exist", json={"alias": "x"}
    )
    assert resp.status_code == 404


# ── Delete ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_non_active(harness):
    created = _create(harness.client).json()
    resp = harness.client.delete(f"/api/v1/accounts/{created['id']}")
    assert resp.status_code == 200
    assert harness.client.get("/api/v1/accounts").json()["accounts"] == []


@pytest.mark.asyncio
async def test_delete_active_succeeds_and_calls_deactivate(harness):
    """Deleting the active account is allowed: container.deactivate() runs
    first (disconnect + clear engines + clear active row), then the row
    is dropped. Frontend boot path handles the resulting no-active state."""
    created = _create(harness.client).json()
    harness.client.post(f"/api/v1/accounts/{created['id']}/activate")
    resp = harness.client.delete(f"/api/v1/accounts/{created['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["was_active"] is True
    assert len(harness.container.deactivate_log) == 1
    # No accounts left + no active row.
    listing = harness.client.get("/api/v1/accounts").json()
    assert listing["accounts"] == []
    assert listing["active_id"] is None


@pytest.mark.asyncio
async def test_delete_unknown_404(harness):
    resp = harness.client.delete("/api/v1/accounts/does-not-exist")
    assert resp.status_code == 404


# ── Activate ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_marks_active_and_calls_container(harness):
    created = _create(harness.client).json()
    resp = harness.client.post(f"/api/v1/accounts/{created['id']}/activate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["connected"] is True
    assert body["authenticated"] is True
    assert harness.container.activate_calls == [created["id"]]

    # /accounts/active now returns it.
    active = harness.client.get("/api/v1/accounts/active").json()
    assert active["active"]["id"] == created["id"]
    assert active["active"]["client_id_tail"] == "2345"


@pytest.mark.asyncio
async def test_activate_unknown_404(harness):
    resp = harness.client.post("/api/v1/accounts/missing/activate")
    assert resp.status_code == 404


# ── Test credentials ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_credentials_validates_payload(harness):
    # Missing client_secret → 422 before we hit the wire.
    resp = harness.client.post(
        "/api/v1/accounts/test-credentials",
        json={"endpoint": "deribit_testnet", "client_id": "x"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_test_credentials_rejects_unknown_endpoint(harness):
    resp = harness.client.post(
        "/api/v1/accounts/test-credentials",
        json={"endpoint": "nope", "client_id": "x", "client_secret": "y"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_test_existing_account_404(harness):
    resp = harness.client.post("/api/v1/accounts/missing/test")
    assert resp.status_code == 404
