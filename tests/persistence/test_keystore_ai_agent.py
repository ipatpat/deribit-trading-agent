"""Tests for KeyStore ai_agent namespace methods."""

import os
import tempfile

import pytest

from deribit_trading.config.key_store import KeyStore


@pytest.fixture
def keystore():
    """Fresh ephemeral keystore for each test."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        path = f.name
    try:
        ks = KeyStore(path, master_password="test-master")
        yield ks
    finally:
        os.unlink(path)


def test_get_returns_none_when_not_configured(keystore):
    assert keystore.get_ai_agent_config() is None
    assert keystore.has_ai_agent_api_key() is False


def test_set_and_get_round_trip(keystore):
    keystore.set_ai_agent_config(
        endpoint="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-plus",
        api_key="sk-secret-key",
    )
    cfg = keystore.get_ai_agent_config()
    assert cfg == {
        "endpoint": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "api_key": "sk-secret-key",
    }


def test_get_public_returns_no_api_key(keystore):
    keystore.set_ai_agent_config(
        endpoint="https://example.com",
        model="glm-4-plus",
        api_key="secret-do-not-leak",
    )
    public = keystore.get_ai_agent_public()
    assert public["endpoint"] == "https://example.com"
    assert public["model"] == "glm-4-plus"
    assert public["api_key_set"] is True
    assert "api_key" not in public


def test_has_api_key_flag(keystore):
    assert keystore.has_ai_agent_api_key() is False
    keystore.set_ai_agent_config(endpoint="x", model="y", api_key="z")
    assert keystore.has_ai_agent_api_key() is True


def test_clear_removes_all(keystore):
    keystore.set_ai_agent_config(endpoint="x", model="y", api_key="z")
    keystore.clear_ai_agent_config()
    assert keystore.get_ai_agent_config() is None
    assert keystore.has_ai_agent_api_key() is False


def test_overwrite_existing(keystore):
    keystore.set_ai_agent_config(endpoint="ep1", model="m1", api_key="k1")
    keystore.set_ai_agent_config(endpoint="ep2", model="m2", api_key="k2")
    cfg = keystore.get_ai_agent_config()
    assert cfg["endpoint"] == "ep2"
    assert cfg["model"] == "m2"
    assert cfg["api_key"] == "k2"


def test_namespace_isolation_from_api_keys(keystore):
    """Setting ai_agent should not affect deribit api_keys."""
    from deribit_trading.config import Environment
    keystore.add_key(Environment.TESTNET, "main", "client_id_x", "secret_y", "scope_z")
    keystore.set_ai_agent_config(endpoint="x", model="y", api_key="ai_key")
    # Both should still be readable
    api_key = keystore.get_key(Environment.TESTNET, "main")
    assert api_key.client_id == "client_id_x"
    assert api_key.client_secret == "secret_y"
    ai = keystore.get_ai_agent_config()
    assert ai["api_key"] == "ai_key"


def test_encryption_roundtrip(keystore):
    """Verify the stored value is encrypted (not plaintext)."""
    import sqlite3
    keystore.set_ai_agent_config(endpoint="ep", model="m", api_key="my-secret-key")
    with sqlite3.connect(keystore._db_path) as conn:
        rows = conn.execute(
            "SELECT key, value_encrypted FROM agent_config WHERE namespace = 'ai_agent'"
        ).fetchall()
    raw_blobs = [r[1] for r in rows]
    # None of the blobs should contain the plaintext
    for blob in raw_blobs:
        assert b"my-secret-key" not in blob
        assert b"ep" not in blob[:5]  # Fernet ciphertexts don't start with plaintext


def test_get_returns_none_if_partial_config(keystore):
    """If only some fields are saved, get should return None (not partial)."""
    import sqlite3
    # Manually insert just one field
    encrypted = keystore._fernet.encrypt(b"endpoint-only")
    with sqlite3.connect(keystore._db_path) as conn:
        conn.execute(
            "INSERT INTO agent_config (namespace, key, value_encrypted) VALUES (?, ?, ?)",
            ("ai_agent", "endpoint", encrypted),
        )
    # Missing model + api_key → should return None
    assert keystore.get_ai_agent_config() is None
