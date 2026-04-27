"""JSON-RPC 2.0 request/response management."""

import asyncio
import itertools
import logging
from typing import Any

from .connection import WebSocketConnection
from .errors import DeribitAPIError, DeribitConnectionError, DeribitTimeoutError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0  # seconds


class JsonRpcManager:
    """Manages JSON-RPC requests over a WebSocket connection."""

    def __init__(self, connection: WebSocketConnection) -> None:
        self._connection = connection
        self._id_counter = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._subscription_handler: Any = None

        # Register ourselves as the message handler
        connection.set_message_handler(self._on_message)

    def set_subscription_handler(
        self, handler: Any
    ) -> None:
        """Set handler for subscription notifications."""
        self._subscription_handler = handler

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if not self._connection.is_connected:
            raise DeribitConnectionError("Not connected")

        request_id = next(self._id_counter)
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        try:
            await self._connection.send(message)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            raise DeribitTimeoutError(
                f"Request {method} (id={request_id}) timed out after {timeout}s"
            )
        finally:
            self._pending.pop(request_id, None)

    def _on_message(self, message: dict[str, Any]) -> None:
        """Handle incoming JSON-RPC messages."""
        # Response to a request (has "id")
        if "id" in message and message["id"] in self._pending:
            request_id = message["id"]
            future = self._pending.get(request_id)
            if future and not future.done():
                if "error" in message:
                    err = message["error"]
                    future.set_exception(
                        DeribitAPIError(
                            code=err.get("code", -1),
                            message=err.get("message", "Unknown error"),
                            data=err.get("data"),
                        )
                    )
                elif "result" in message:
                    future.set_result(message["result"])
                else:
                    future.set_result(message)
            return

        # Subscription notification (method == "subscription")
        if message.get("method") == "subscription" and self._subscription_handler:
            params = message.get("params", {})
            channel = params.get("channel", "")
            data = params.get("data")
            handler = self._subscription_handler
            if callable(handler):
                handler(channel, data)
