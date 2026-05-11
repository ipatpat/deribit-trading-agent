"""Encrypted API key storage with least-privilege selection."""

import base64
import logging
import sqlite3
from dataclasses import dataclass

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .env_manager import Environment

logger = logging.getLogger(__name__)

SALT = b"deribit-trading-keystore-v1"


def _derive_key(master_password: str) -> bytes:
    """Derive a Fernet key from a master password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


@dataclass
class ApiKeyInfo:
    """API key metadata (without the secret)."""

    name: str
    env: str
    client_id: str
    scopes: str  # comma-separated scopes


@dataclass
class ApiKeyFull:
    """API key with decrypted secret."""

    name: str
    env: str
    client_id: str
    client_secret: str
    scopes: str


class KeyStore:
    """Encrypted API key storage backed by SQLite."""

    def __init__(self, db_path: str, master_password: str) -> None:
        self._db_path = db_path
        self._fernet = Fernet(_derive_key(master_password))
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    name TEXT NOT NULL,
                    env TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    client_secret_encrypted BLOB NOT NULL,
                    scopes TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (name, env)
                )
            """)
            # AI Agent config — single namespace, key-value with encrypted values.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_config (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_encrypted BLOB NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
            """)

    def add_key(
        self,
        env: Environment,
        name: str,
        client_id: str,
        client_secret: str,
        scopes: str = "",
    ) -> None:
        """Add or replace an API key."""
        encrypted = self._fernet.encrypt(client_secret.encode())
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO api_keys
                   (name, env, client_id, client_secret_encrypted, scopes)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, env, client_id, encrypted, scopes),
            )
        logger.info("API key '%s' added for env '%s'", name, env)

    def remove_key(self, env: Environment, name: str) -> bool:
        """Remove an API key. Returns True if key existed."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM api_keys WHERE name = ? AND env = ?", (name, env)
            )
            return cursor.rowcount > 0

    def list_keys(self, env: Environment | None = None) -> list[ApiKeyInfo]:
        """List API keys (without secrets)."""
        with sqlite3.connect(self._db_path) as conn:
            if env:
                rows = conn.execute(
                    "SELECT name, env, client_id, scopes FROM api_keys WHERE env = ?",
                    (env,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT name, env, client_id, scopes FROM api_keys"
                ).fetchall()
        return [
            ApiKeyInfo(name=r[0], env=r[1], client_id=r[2], scopes=r[3])
            for r in rows
        ]

    def get_key(self, env: Environment, name: str) -> ApiKeyFull | None:
        """Get a specific key with decrypted secret."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """SELECT name, env, client_id, client_secret_encrypted, scopes
                   FROM api_keys WHERE name = ? AND env = ?""",
                (name, env),
            ).fetchone()

        if not row:
            return None

        secret = self._fernet.decrypt(row[3]).decode()
        return ApiKeyFull(
            name=row[0], env=row[1], client_id=row[2], client_secret=secret, scopes=row[4]
        )

    def get_key_for_scope(self, env: Environment, required_scope: str) -> ApiKeyFull:
        """Select the least-privileged key that has the required scope.

        Prefers read-only keys for read operations, trading keys for trade operations.
        """
        keys = self._get_all_keys(env)
        if not keys:
            raise ValueError(f"No API keys configured for environment '{env}'")

        # Score keys: fewer scopes = more restricted = preferred
        def scope_score(key: ApiKeyFull) -> int:
            scopes = key.scopes.split(",") if key.scopes else []
            return len(scopes)

        # Filter keys that have the required scope
        matching = [
            k for k in keys
            if required_scope in k.scopes or not k.scopes  # empty scopes = full access
        ]

        if not matching:
            raise ValueError(
                f"No API key with scope '{required_scope}' found for environment '{env}'"
            )

        # Return the one with fewest scopes (least privilege)
        matching.sort(key=scope_score)
        return matching[0]

    def _get_all_keys(self, env: Environment) -> list[ApiKeyFull]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """SELECT name, env, client_id, client_secret_encrypted, scopes
                   FROM api_keys WHERE env = ?""",
                (env,),
            ).fetchall()
        return [
            ApiKeyFull(
                name=r[0],
                env=r[1],
                client_id=r[2],
                client_secret=self._fernet.decrypt(r[3]).decode(),
                scopes=r[4],
            )
            for r in rows
        ]

    # ── AI Agent config (ai_agent namespace) ─────────────────────────────────
    _AI_AGENT_NS = "ai_agent"
    _AI_AGENT_KEYS = ("endpoint", "model", "api_key")

    def get_ai_agent_config(self) -> dict[str, str] | None:
        """Return decrypted AI agent config dict, or None if not configured.

        Returns dict with keys: endpoint, model, api_key. Returns None if any
        of the three is missing.
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT key, value_encrypted FROM agent_config WHERE namespace = ?",
                (self._AI_AGENT_NS,),
            ).fetchall()
        if not rows:
            return None
        cfg = {row[0]: self._fernet.decrypt(row[1]).decode() for row in rows}
        if not all(k in cfg for k in self._AI_AGENT_KEYS):
            return None
        return cfg

    def set_ai_agent_config(self, endpoint: str, model: str, api_key: str) -> None:
        """Encrypt and store AI agent config."""
        with sqlite3.connect(self._db_path) as conn:
            for key, value in (("endpoint", endpoint), ("model", model), ("api_key", api_key)):
                encrypted = self._fernet.encrypt(value.encode())
                conn.execute(
                    """INSERT OR REPLACE INTO agent_config
                       (namespace, key, value_encrypted) VALUES (?, ?, ?)""",
                    (self._AI_AGENT_NS, key, encrypted),
                )
        logger.info("AI agent config saved (model=%s)", model)

    def has_ai_agent_api_key(self) -> bool:
        """Quick check whether api_key is set (for /settings/ai-agent GET)."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_config WHERE namespace = ? AND key = ?",
                (self._AI_AGENT_NS, "api_key"),
            ).fetchone()
        return row is not None

    def get_ai_agent_public(self) -> dict[str, str | bool | None]:
        """Return non-secret AI agent config for frontend display.

        Returns: {endpoint: str | None, model: str | None, api_key_set: bool}
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT key, value_encrypted FROM agent_config WHERE namespace = ?",
                (self._AI_AGENT_NS,),
            ).fetchall()
        cfg: dict[str, str] = {}
        for row in rows:
            cfg[row[0]] = self._fernet.decrypt(row[1]).decode()
        return {
            "endpoint": cfg.get("endpoint"),
            "model": cfg.get("model"),
            "api_key_set": "api_key" in cfg,
        }

    def clear_ai_agent_config(self) -> None:
        """Delete all AI agent config rows."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "DELETE FROM agent_config WHERE namespace = ?",
                (self._AI_AGENT_NS,),
            )
        logger.info("AI agent config cleared")
