"""WebSocket handler for Jukebox media player."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import json
import logging
import ssl
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class JukeboxWebSocket:
    """WebSocket connection manager for Jukebox real-time updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        ws_url: str,
        auth_headers: dict[str, str],
        use_ssl: bool,
        data_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the WebSocket handler."""
        self.hass = hass
        self.ws_url = ws_url
        self.auth_headers = auth_headers
        self.use_ssl = use_ssl
        self.data_callback = data_callback

        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._reconnect_interval = 5

    @property
    def is_connected(self) -> bool:
        """Return True if websocket is connected."""
        return self._websocket is not None and not self._websocket.closed

    async def start(self) -> None:
        """Start the websocket connection."""
        if self._task and not self._task.done():
            return

        self._task = asyncio.create_task(self._loop())
        _LOGGER.debug("Started websocket connection task")

    async def stop(self) -> None:
        """Stop the websocket connection."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._websocket and not self._websocket.closed:
            await self._websocket.close()
            self._websocket = None

        _LOGGER.debug("Stopped websocket connection")

    async def _loop(self) -> None:
        """Main websocket connection loop with reconnection."""
        while True:
            try:
                await self._connect()
            except asyncio.CancelledError:
                _LOGGER.debug("Websocket loop cancelled")
                break
            except Exception as e:
                _LOGGER.error("Websocket connection failed: %s", e)

            # Wait before reconnecting
            try:
                await asyncio.sleep(self._reconnect_interval)
            except asyncio.CancelledError:
                break

    async def _connect(self) -> None:
        """Connect to the websocket and handle messages."""
        session = async_get_clientsession(self.hass)

        # Configure SSL context for WSS
        ssl_context = False
        if self.use_ssl:
            ssl_context = await self.hass.async_add_executor_job(
                ssl.create_default_context
            )

        _LOGGER.debug("Connecting to websocket: %s", self.ws_url)

        try:
            # Try connecting with basic auth headers first
            self._websocket = await session.ws_connect(
                self.ws_url,
                headers=self.auth_headers,
                ssl=ssl_context,
            )

            _LOGGER.warning("🔗 WEBSOCKET CONNECTED to jukebox successfully!")

            # Listen for messages
            async for msg in self._websocket:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.PING:
                    _LOGGER.debug("Received websocket PING")
                elif msg.type == aiohttp.WSMsgType.PONG:
                    _LOGGER.debug("Received websocket PONG")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("Websocket error: %s", self._websocket.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    _LOGGER.info("Websocket closed")
                    break

        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                _LOGGER.error(
                    "Websocket authentication failed - check NPM basic auth credentials"
                )
                await self._try_fallback_connection(session, ssl_context)
            else:
                _LOGGER.error("Websocket HTTP error %s: %s", e.status, e)
        except asyncio.CancelledError:
            _LOGGER.debug("Websocket connection cancelled")
            raise
        except aiohttp.ClientError as e:
            _LOGGER.error("Websocket client error: %s", e)
        except Exception as e:
            _LOGGER.error("Websocket connection error: %s", e)
        finally:
            if self._websocket and not self._websocket.closed:
                await self._websocket.close()
            self._websocket = None

    async def _try_fallback_connection(
        self, session: aiohttp.ClientSession, ssl_context: ssl.SSLContext | bool
    ) -> None:
        """Try connecting without auth headers as fallback."""
        try:
            _LOGGER.debug("Trying websocket connection without auth headers")
            self._websocket = await session.ws_connect(self.ws_url, ssl=ssl_context)
            _LOGGER.info("Websocket connected without auth")

            # Continue with message processing
            async for msg in self._websocket:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text_message(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.PING,
                    aiohttp.WSMsgType.PONG,
                ):
                    continue
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("Websocket error: %s", self._websocket.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    _LOGGER.info("Websocket closed")
                    break

        except Exception as fallback_e:
            _LOGGER.error("Websocket fallback connection also failed: %s", fallback_e)

    async def _handle_text_message(self, message_data: str) -> None:
        """Handle incoming text message from websocket."""
        try:
            _LOGGER.debug("RAW WEBSOCKET MESSAGE: %s", message_data)

            data = json.loads(message_data)
            _LOGGER.debug("PARSED WEBSOCKET DATA: %s", data)

            # Handle typed messages from server
            msg_type = data.get("type")
            payload = data.get("payload", {})

            _LOGGER.debug("WebSocket message type: %s", msg_type)

            # Only process current_track messages, ignore ping and other types
            if msg_type == "current_track":
                _LOGGER.debug("✅ PROCESSING current_track message")
                try:
                    await self.data_callback(payload)
                except Exception as update_error:
                    _LOGGER.error("Error processing websocket data: %s", update_error)
            elif msg_type == "ping":
                _LOGGER.debug("Received server ping, ignoring")
            else:
                _LOGGER.debug("Ignoring websocket message type: %s", msg_type)

        except json.JSONDecodeError:
            _LOGGER.debug(
                "❌ IGNORING non-JSON websocket message: %s", message_data.strip()
            )

    @staticmethod
    def is_valid_jukebox_data(data: dict[str, Any]) -> bool:
        """Validate that the websocket data contains expected jukebox structure."""
        if not isinstance(data, dict):
            _LOGGER.debug("Invalid data: not a dict - %s", type(data))
            return False

        # Log what we received for debugging
        _LOGGER.debug("🔍 VALIDATING websocket data keys: %s", list(data.keys()))

        # Check for ping messages first and reject them
        if data.get("status") == "ping":
            _LOGGER.debug("❌ VALIDATION FAILED: ignoring ping message")
            return False

        # Must have at least one expected key from jukebox data structure
        expected_keys = ["status", "current_track", "playlist", "volume", "elapsed"]
        if not any(key in data for key in expected_keys):
            _LOGGER.debug(
                "❌ VALIDATION FAILED: no expected keys found. Got: %s",
                list(data.keys()),
            )
            return False

        # If status exists, it should be a valid player status
        if "status" in data:
            status = data["status"]
            valid_statuses = [
                "playing",
                "paused",
                "stopped",
                "idle",
                "PLAY",
                "PAUSE",
                "STOP",
            ]
            if status not in valid_statuses:
                _LOGGER.debug(
                    "❌ VALIDATION FAILED: invalid status '%s' (expected: %s)",
                    status,
                    valid_statuses,
                )
                return False

        # If current_track exists, validate it
        if "current_track" in data:
            current_track = data["current_track"]
            if current_track is not None and isinstance(current_track, dict):
                if current_track:  # Non-empty dict
                    track_fields = ["artist", "title", "album", "duration", "track_id"]
                    if not any(field in current_track for field in track_fields):
                        _LOGGER.debug(
                            "❌ VALIDATION FAILED: current_track has no recognized fields - %s",
                            list(current_track.keys()),
                        )
                        return False

        _LOGGER.debug("✅ VALIDATION PASSED")
        return True
