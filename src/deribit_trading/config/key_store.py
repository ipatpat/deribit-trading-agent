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
