"""Authentication management for Deribit API."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rpc import JsonRpcManager

logger = logging.getLogger(__name__)

TOKEN_REFRESH_BUFFER = 60  # Refresh token this many seconds before expiry


class AuthManager:
    """Manages Deribit authentication with automatic token refresh."""

    def __init__(self, rpc: "JsonRpcManager") -> None:
        self._rpc = rpc
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: float = 0.0
        self._refresh_task: asyncio.Task[None] | None = None
        self._client_id: str | None = None
        self._client_secret: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None and time.time() < self._token_expiry

    @property
    def access_token(self) -> str | None:
        return self._access_token

    async def authenticate(self, client_id: str, client_secret: str) -> None:
        """Authenticate using client credentials."""
        self._client_id = client_id
        self._client_secret = client_secret

        result = await self._rpc.call("public/auth", {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        })

        self._process_auth_result(result)
        self._start_refresh_timer()
        logger.info("Authenticated successfully (expires in %ds)", result.get("expires_in", 0))

    async def reauthenticate(self) -> None:
        """Re-authenticate using stored credentials (for reconnection)."""
        if self._client_id and self._client_secret:
            await self.authenticate(self._client_id, self._client_secret)

    async def logout(self) -> None:
        """Invalidate current session."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        if self._access_token:
            try:
                await self._rpc.call("private/logout", {})
            except Exception:
                pass

        self._access_token = None
        self._refresh_token = None
        self._token_expiry = 0.0

    def _process_auth_result(self, result: dict) -> None:
        self._access_token = result["access_token"]
        self._refresh_token = result["refresh_token"]
        self._token_expiry = time.time() + result.get("expires_in", 900)

    def _start_refresh_timer(self) -> None:
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        """Periodically refresh the access token before it expires."""
        try:
            while True:
                sleep_time = max(
                    self._token_expiry - time.time() - TOKEN_REFRESH_BUFFER, 1
                )
                await asyncio.sleep(sleep_time)

                if not self._refresh_token:
                    break

                try:
                    result = await self._rpc.call("public/auth", {
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                    })
                    self._process_auth_result(result)
                    logger.debug("Token refreshed successfully")
                except Exception as e:
                    logger.error("Token refresh failed: %s", e)
                    # Try full re-auth
                    if self._client_id and self._client_secret:
                        await self.authenticate(self._client_id, self._client_secret)
        except asyncio.CancelledError:
            pass
