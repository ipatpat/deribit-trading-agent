"""Multi-account management — replaces the legacy EnvManager.

Owns the *active account* state and the three known Deribit endpoints. The
WebSocket client / SmartOrderEngine / PortfolioService lifecycle hangs off
this module: activating a different account triggers disconnect → reconnect
+ engine reset.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..persistence import AccountRepo, Database
    from .key_store import KeyStore

logger = logging.getLogger(__name__)


# ── Endpoint registry ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EndpointConfig:
    """One Deribit endpoint (ws + http URL pair) plus its display label."""

    ws_url: str
    http_url: str
    label: str
    is_production: bool


ENDPOINTS: dict[str, EndpointConfig] = {
    "deribit_prod": EndpointConfig(
        ws_url="wss://www.deribit.com/ws/api/v2",
        http_url="https://www.deribit.com/api/v2",
        label="deribit.com (Production)",
        is_production=True,
    ),
    "tibired_prod": EndpointConfig(
        ws_url="wss://www.tibired.com/ws/api/v2",
        http_url="https://www.tibired.com/api/v2",
        label="tibired.com (Production)",
        is_production=True,
    ),
    "deribit_testnet": EndpointConfig(
        ws_url="wss://test.deribit.com/ws/api/v2",
        http_url="https://test.deribit.com/api/v2",
        label="test.deribit.com (Paper Trade)",
        is_production=False,
    ),
}


def resolve_endpoint(endpoint_id: str) -> EndpointConfig:
    """Return the EndpointConfig for a key; raises ValueError on unknown."""
    cfg = ENDPOINTS.get(endpoint_id)
    if cfg is None:
        raise ValueError(
            f"Unknown endpoint '{endpoint_id}'. Valid keys: {list(ENDPOINTS.keys())}"
        )
    return cfg


# ── Account record (light, sans secret) ──────────────────────────────────────
@dataclass
class Account:
    """A trading account profile. `client_secret` is intentionally absent so
    instances of this class can be safely logged / serialised."""

    id: str  # uuid
    alias: str
    endpoint: str  # one of ENDPOINTS keys
    client_id: str
    created_at: int
    last_used_at: int | None = None


# ── AccountManager (active state + activation flow) ──────────────────────────
class AccountSwitchError(Exception):
    """Raised when activate() fails partway. AccountManager rolls back."""


class AccountManager:
    """Active-account state machine. Single active account at a time.

    Construction is decoupled from the actual reconnect logic — pass a
    `reconnect_callback` that receives the new Account + decrypted secret and
    performs the actual WebSocket / engine wiring. This keeps AccountManager
    free of import cycles with TradingService / DeribitClient.
    """

    def __init__(self) -> None:
        self._active_account: Account | None = None
        self._switching = False
        self._lock = asyncio.Lock()

    @property
    def active(self) -> Account | None:
        return self._active_account

    @property
    def active_id(self) -> str | None:
        return self._active_account.id if self._active_account else None

    @property
    def is_switching(self) -> bool:
        return self._switching

    @property
    def ws_url(self) -> str | None:
        if not self._active_account:
            return None
        return resolve_endpoint(self._active_account.endpoint).ws_url

    @property
    def http_url(self) -> str | None:
        if not self._active_account:
            return None
        return resolve_endpoint(self._active_account.endpoint).http_url

    def is_production(self) -> bool:
        """Derived from the active account's endpoint."""
        if not self._active_account:
            return False
        return resolve_endpoint(self._active_account.endpoint).is_production

    @property
    def current_env(self) -> str:
        """Backward-compatible env label for callers that still log it.

        Returns "production" / "testnet" derived from the active endpoint, or
        "none" when no active account.
        """
        if not self._active_account:
            return "none"
        return "production" if self.is_production() else "testnet"

    def set_active_unchecked(self, account: Account | None) -> None:
        """Direct setter, used only at boot (skip the activate flow). Higher
        layers (activate()) must call reconnect_callback themselves."""
        self._active_account = account

    async def activate(
        self,
        new_account: Account,
        client_secret: str,
        reconnect_callback: Any,  # async callable (Account, secret) -> None
        post_reset_callbacks: list[Any] | None = None,  # async callables (Account) -> None
    ) -> Account:
        """Switch active account.

        Steps (per design.md decision 4):
          1. Mark `_switching = True`
          2. reconnect_callback handles: disconnect old client, reset pending
             confirmations, reset SmartOrderEngine, reset PortfolioService
             cache, build new client, authenticate
          3. Update `_active_account`
          4. Fire post_reset callbacks (notify downstream listeners)
          5. Mark `_switching = False`

        On failure raises AccountSwitchError, leaves _active_account at old
        value.
        """
        if self._switching:
            raise AccountSwitchError("Account switch already in progress")

        async with self._lock:
            self._switching = True
            previous = self._active_account
            try:
                await reconnect_callback(new_account, client_secret)
                self._active_account = new_account
                for cb in post_reset_callbacks or []:
                    try:
                        await cb(new_account)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "post_reset_callback failed on account switch"
                        )
                logger.info(
                    "Account switched: %s → %s",
                    previous.alias if previous else "<none>",
                    new_account.alias,
                )
                return new_account
            except Exception as exc:  # noqa: BLE001
                # reconnect failed — keep previous active; caller may retry
                self._active_account = previous
                raise AccountSwitchError(
                    f"Switch to {new_account.alias!r} failed: {exc}"
                ) from exc
            finally:
                self._switching = False


# ── Bootstrap: import legacy api_keys → accounts ─────────────────────────────


_ENV_TO_ENDPOINT_DEFAULT = {
    # Match the legacy EnvManager default (`_production_endpoint = "tibired"`).
    "production": "tibired_prod",
    "testnet": "deribit_testnet",
}


async def bootstrap_accounts_from_keystore(
    db: "Database",
    account_repo: "AccountRepo",
    key_store: "KeyStore",
) -> dict[str, str]:
    """One-shot v3→v4 data migration.

    If the accounts table is empty AND the legacy api_keys table has rows,
    create a `default-{env}` account per env using the existing encrypted
    secret (same Fernet → blob is portable), then rewrite history rows'
    account_id columns from the legacy env string to the new uuid.

    Returns the env→account_id mapping (empty dict if no migration ran).
    Idempotent: subsequent calls see non-empty accounts table and exit.
    """
    existing = await account_repo.list_all()
    if existing:
        return {}  # already migrated or fresh install with manual accounts

    legacy = key_store.export_legacy_api_keys()
    if not legacy:
        return {}  # truly fresh install, nothing to migrate

    env_to_id: dict[str, str] = {}
    now = int(time.time() * 1000)
    for entry in legacy:
        env_str = str(entry.env)
        if env_str in env_to_id:
            # Multiple keys for same env (rare) — first one wins as default
            continue
        endpoint = _ENV_TO_ENDPOINT_DEFAULT.get(env_str)
        if endpoint is None:
            logger.warning(
                "Skipping legacy key for unknown env %r — manual reconfigure required",
                env_str,
            )
            continue
        alias = f"default-{env_str}"
        # Avoid alias collisions on re-runs (shouldn't happen because we
        # bailed on existing, but defensive)
        try:
            existing_by_alias = await account_repo.get_by_alias(alias)
        except Exception:  # noqa: BLE001
            existing_by_alias = None
        suffix = 1
        while existing_by_alias is not None:
            alias = f"default-{env_str}-{suffix}"
            suffix += 1
            existing_by_alias = await account_repo.get_by_alias(alias)

        new_id = str(uuid.uuid4())
        secret_blob = key_store.encrypt(entry.client_secret)
        await account_repo.create(
            account_id=new_id,
            alias=alias,
            endpoint=endpoint,
            client_id=entry.client_id,
            client_secret_encrypted=secret_blob,
            created_at=now,
        )
        env_to_id[env_str] = new_id
        logger.info(
            "Migrated legacy %s key → account '%s' (id=%s, endpoint=%s)",
            env_str, alias, new_id, endpoint,
        )

    # Backfill history rows: account_id column still contains old env strings
    if env_to_id:
        await db.backfill_history_account_ids(env_to_id)
        # Pick an active account: prefer testnet (safer default), else the
        # first migrated entry.
        if "testnet" in env_to_id:
            await account_repo.set_active(env_to_id["testnet"])
            await account_repo.touch_last_used(env_to_id["testnet"], now)
        else:
            first_id = next(iter(env_to_id.values()))
            await account_repo.set_active(first_id)
            await account_repo.touch_last_used(first_id, now)

    return env_to_id
