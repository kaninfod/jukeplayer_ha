"""WebSocket handler for the Jukeplayer media player."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import json
import logging
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
        data_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
        get_device_id: Callable[[], Coroutine[Any, Any, str | None]] | None = None,
    ) -> None:
        """Initialize the WebSocket handler.

        get_device_id (optional) is awaited before every (re)connect so the
        register payload carries the backend's current default speaker — that
        is what lands the client on a speaker and keeps current_track
        broadcasts flowing. No hardcoded speaker name.
        """
        self.hass = hass
        self.ws_url = ws_url
        self.data_callback = data_callback
        self.get_device_id = get_device_id
        self.client_id: str | None = None

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

        _LOGGER.debug("Connecting to websocket: %s", self.ws_url)

        try:
            # Try connecting
            self._websocket = await session.ws_connect(
                self.ws_url,
            )

            _LOGGER.warning("🔗 WEBSOCKET CONNECTED to jukebox successfully!")

            # Resolve the default speaker so the registration lands the
            # client on a speaker (current_track broadcasts ride that
            # assignment). None → backend default fallback; retried on the
            # next reconnect.
            device_id = None
            if self.get_device_id:
                try:
                    device_id = await self.get_device_id()
                except Exception as e:
                    _LOGGER.debug("Default speaker lookup failed: %s", e)

            # Register as a Home Assistant client
            await self._websocket.send_json(
                {
                    "type": "register_client",
                    "payload": {
                        "client_type": "home_assistant",
                        "client_name": "Home Assistant",
                        "capabilities": ["websocket_status"],
                        "device_id": device_id,
                        "client_id": self.client_id
                    },
                }
            )

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
            if e.status in (401, 403):
                _LOGGER.error(
                    "Websocket connection failed with HTTP %s: Access forbidden or unauthorized",
                    e.status,
                )
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
            elif msg_type == "register_response":
                status = payload.get("status")
                self.client_id = payload.get("client_id")
                if status == "success":
                    _LOGGER.info(
                        "Registered with Jukebox backend as client %s", self.client_id
                    )
                else:
                    _LOGGER.error(
                        "Registration with Jukebox backend failed: %s",
                        payload.get("message"),
                    )
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

    async def send_message(self, message_type: str, payload: dict[str, Any]) -> bool:
            """Send a message over the WebSocket connection if it is active."""
            if not self.is_connected or self._websocket is None:
                _LOGGER.error("Cannot send message: WebSocket is disconnected")
                return False

            try:
                message = {
                    "type": message_type,
                    "payload": payload
                }
                _LOGGER.debug("Sending WebSocket message: %s", message)
                await self._websocket.send_json(message)
                return True
            except Exception as e:
                _LOGGER.error("Failed to send WebSocket message: %s", e)
                return False
