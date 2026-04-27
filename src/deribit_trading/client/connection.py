"""WebSocket connection management with heartbeat and reconnection."""

import asyncio
import json
import logging
from enum import StrEnum
from typing import Any, Callable

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15  # seconds
HEARTBEAT_RESPONSE_TIMEOUT = 10  # seconds
MAX_RECONNECT_DELAY = 60  # seconds
INITIAL_RECONNECT_DELAY = 1  # seconds


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class WebSocketConnection:
    """Manages a WebSocket connection to Deribit with heartbeat and auto-reconnect."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._ws: ClientConnection | None = None
        self._state = ConnectionState.DISCONNECTED
        self._message_handler: Callable[[dict[str, Any]], None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._reconnect_delay = INITIAL_RECONNECT_DELAY
        self._should_reconnect = True
        self._on_reconnect: Callable[[], Any] | None = None

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._ws is not None

    def set_message_handler(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self._message_handler = handler

    def set_on_reconnect(self, callback: Callable[[], Any]) -> None:
        self._on_reconnect = callback

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        if self.is_connected:
            return

        self._state = ConnectionState.CONNECTING
        self._should_reconnect = True

        try:
            self._ws = await websockets.connect(self.url)
            self._state = ConnectionState.CONNECTED
            self._reconnect_delay = INITIAL_RECONNECT_DELAY
            logger.info("WebSocket connected to %s", self.url)

            self._receive_task = asyncio.create_task(self._receive_loop())
            await self._enable_heartbeat()

        except Exception:
            self._state = ConnectionState.DISCONNECTED
            raise

    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        self._should_reconnect = False

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._state = ConnectionState.DISCONNECTED
        logger.info("WebSocket disconnected")

    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON message over the WebSocket."""
        if not self.is_connected or self._ws is None:
            raise ConnectionError("WebSocket is not connected")

        await self._ws.send(json.dumps(message))

    async def _enable_heartbeat(self) -> None:
        """Enable server-side heartbeat via Deribit API."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Respond to heartbeat test requests from server."""
        # The actual heartbeat handling is done in _receive_loop
        # when we receive test_request notifications.
        # This task sends periodic /public/set_heartbeat to enable it.
        try:
            while self.is_connected:
                await self.send({
                    "jsonrpc": "2.0",
                    "id": -1,
                    "method": "public/set_heartbeat",
                    "params": {"interval": HEARTBEAT_INTERVAL},
                })
                await asyncio.sleep(HEARTBEAT_INTERVAL * 3)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Heartbeat loop error: %s", e)

    async def _receive_loop(self) -> None:
        """Continuously receive and dispatch messages."""
        try:
            while self.is_connected and self._ws is not None:
                try:
                    raw = await self._ws.recv()
                    message = json.loads(raw)
                    await self._handle_message(message)
                except websockets.ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    break
        except asyncio.CancelledError:
            return

        # Connection lost — attempt reconnect
        if self._should_reconnect:
            self._state = ConnectionState.DISCONNECTED
            await self._reconnect()

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Route incoming messages."""
        # Handle heartbeat test_request
        method = message.get("method")
        if method == "heartbeat":
            if message.get("params", {}).get("type") == "test_request":
                await self.send({
                    "jsonrpc": "2.0",
                    "id": -2,
                    "method": "public/test",
                    "params": {},
                })
                return

        # Forward to handler
        if self._message_handler:
            self._message_handler(message)

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        self._state = ConnectionState.RECONNECTING
        attempt = 0

        while self._should_reconnect:
            attempt += 1
            logger.info(
                "Reconnection attempt %d (delay: %.1fs)", attempt, self._reconnect_delay
            )

            try:
                await asyncio.sleep(self._reconnect_delay)
                self._ws = await websockets.connect(self.url)
                self._state = ConnectionState.CONNECTED
                self._reconnect_delay = INITIAL_RECONNECT_DELAY
                logger.info("Reconnected successfully")

                self._receive_task = asyncio.create_task(self._receive_loop())
                await self._enable_heartbeat()

                # Notify for re-auth and re-subscribe
                if self._on_reconnect:
                    result = self._on_reconnect()
                    if asyncio.iscoroutine(result):
                        await result

                return

            except Exception as e:
                logger.warning("Reconnection attempt %d failed: %s", attempt, e)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, MAX_RECONNECT_DELAY
                )
