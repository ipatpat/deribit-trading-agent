"""Tests for /api/v1/settings/ai-agent and /api/v1/agent/* REST endpoints.

Uses FastAPI TestClient with a fully mocked ServiceContainer + KeyStore.
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from deribit_trading.config.key_store import KeyStore
from deribit_trading.rest_api import create_rest_app


@pytest.fixture
def keystore():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        path = f.name
    try:
        ks = KeyStore(path, master_password="test")
        yield ks
    finally:
        os.unlink(path)


@pytest.fixture
def client(keystore):
    """Build TestClient with a mocked container exposing the keystore."""
    container = MagicMock()
    container.key_store = keystore
    container.market_data = MagicMock()
    container.trading = MagicMock()
    container.portfolio = MagicMock()
    container.smart_engine = MagicMock()

    env_manager = MagicMock()
    env_manager.current_env = "testnet"

    app = create_rest_app(
        market_data=MagicMock(),
        trading=MagicMock(),
        portfolio=MagicMock(),
        env_manager=env_manager,
        smart_engine=MagicMock(),
        risk_manager=MagicMock(),
        candle_repo=None,
        container=container,
    )
    return TestClient(app)


def test_get_ai_agent_empty(client):
    """When nothing is configured, returns nulls + api_key_set=False."""
    r = client.get("/api/v1/settings/ai-agent")
    assert r.status_code == 200
    data = r.json()
    assert data["endpoint"] is None
    assert data["model"] is None
    assert data["api_key_set"] is False


def test_post_ai_agent_saves_encrypted(client):
    r = client.post(
        "/api/v1/settings/ai-agent",
        json={"endpoint": "https://x", "model": "glm-4-plus", "api_key": "secret"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["api_key_set"] is True

    # GET should now return public config but never the secret
    r2 = client.get("/api/v1/settings/ai-agent")
    assert r2.status_code == 200
    pub = r2.json()
    assert pub["endpoint"] == "https://x"
    assert pub["model"] == "glm-4-plus"
    assert pub["api_key_set"] is True
    assert "api_key" not in pub
    assert "secret" not in json.dumps(pub)


def test_post_ai_agent_validates_required_fields(client):
    r = client.post("/api/v1/settings/ai-agent", json={"endpoint": "x"})
    assert r.status_code == 400


def test_delete_ai_agent_clears(client):
    client.post(
        "/api/v1/settings/ai-agent",
        json={"endpoint": "x", "model": "y", "api_key": "z"},
    )
    r = client.delete("/api/v1/settings/ai-agent")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/api/v1/settings/ai-agent")
    assert r2.json()["api_key_set"] is False


def test_test_connection_validates_required(client):
    r = client.post("/api/v1/agent/test", json={"endpoint": "x"})
    assert r.status_code == 400


def test_test_connection_returns_failure_for_bad_key(client, monkeypatch):
    """Mock test_connection to return failure."""
    from deribit_trading.agent import loop as loop_mod

    async def _mock_test(endpoint, model, api_key, timeout=10.0):
        return {"ok": False, "code": "auth_failed", "error": "invalid key"}

    monkeypatch.setattr(loop_mod, "test_connection", _mock_test)
    r = client.post(
        "/api/v1/agent/test",
        json={"endpoint": "x", "model": "y", "api_key": "bad"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "auth_failed"


def test_chat_returns_503_when_not_configured(client):
    """If no AI config and no env fallback, /agent/chat returns 503."""
    # Ensure env vars don't fallback
    import os as _os
    _os.environ.pop("GLM_API_KEY", None)
    r = client.post(
        "/api/v1/agent/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_env_fallback_flag_set(client, monkeypatch):
    """When DEEPSEEK_API_KEY env var set, env_fallback_available=True in GET response."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    r = client.get("/api/v1/settings/ai-agent")
    data = r.json()
    assert data["env_fallback_available"] is True


def test_env_fallback_glm_legacy(client, monkeypatch):
    """Legacy GLM_API_KEY env var still works as fallback."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("GLM_API_KEY", "legacy-key")
    r = client.get("/api/v1/settings/ai-agent")
    data = r.json()
    assert data["env_fallback_available"] is True


def test_list_models_validates_required(client):
    """POST /agent/list-models requires endpoint + api_key."""
    r = client.post("/api/v1/agent/list-models", json={"endpoint": "x"})
    assert r.status_code == 400


def test_list_models_returns_list_on_success(client, monkeypatch):
    """Mock list_models to return a valid response."""
    from deribit_trading.agent import llm_client

    async def _mock_list(endpoint, api_key, timeout=10.0):
        return {"ok": True, "models": ["deepseek-chat", "deepseek-reasoner"]}

    monkeypatch.setattr(llm_client, "list_models", _mock_list)
    r = client.post(
        "/api/v1/agent/list-models",
        json={"endpoint": "https://api.deepseek.com", "api_key": "sk-test"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "deepseek-chat" in data["models"]


def test_list_models_returns_error_on_auth_failure(client, monkeypatch):
    from deribit_trading.agent import llm_client

    async def _mock_list(endpoint, api_key, timeout=10.0):
        return {"ok": False, "code": "auth_failed", "error": "invalid key"}

    monkeypatch.setattr(llm_client, "list_models", _mock_list)
    r = client.post(
        "/api/v1/agent/list-models",
        json={"endpoint": "https://api.deepseek.com", "api_key": "bad"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "auth_failed"
