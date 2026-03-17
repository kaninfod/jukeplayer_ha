"""API client for Jukebox media player."""

from __future__ import annotations

import logging
import ssl
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class JukeboxAPIClient:
    """Jukebox API client for making requests to the backend."""

    def __init__(
        self,
        hass: HomeAssistant | None,
        host: str,
        port: int,
        use_ssl: bool,
        auth_headers: dict[str, str],
    ) -> None:
        """Initialize the API client."""
        self.hass: HomeAssistant | None = hass
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.auth_headers = auth_headers

        # Build API base URL
        protocol = "https" if use_ssl else "http"
        if (protocol == "https" and port == 443) or (protocol == "http" and port == 80):
            self.api_base = f"{protocol}://{host}/api"
        else:
            self.api_base = f"{protocol}://{host}:{port}/api"

    async def make_request(
        self,
        endpoint: str,
        method: str = "POST",
        params: dict[str, Any] | None = None,
        return_json: bool = False,
    ) -> bool | dict[str, Any] | list[Any]:
        """Make an authenticated request to the Jukebox API.

        Args:
            endpoint: API endpoint (e.g., "status", "play", "volume_set")
            method: HTTP method ("GET" or "POST")
            params: Query parameters to include in the request
            return_json: If True, return the JSON response; otherwise return success bool

        Returns:
            If return_json is True: dict/list with JSON response (empty dict on error)
            If return_json is False: bool indicating success (status < 400)
        """
        try:
            if not self.hass:
                _LOGGER.error("HomeAssistant instance not set on API client")
                return {} if return_json else False

            session = async_get_clientsession(self.hass)
            url = f"{self.api_base}/{endpoint}"

            # Configure SSL context for HTTPS requests
            ssl_context = False
            if self.use_ssl:
                # Run blocking SSL context creation in executor
                ssl_context = await self.hass.async_add_executor_job(
                    ssl.create_default_context
                )

            # Make the request
            request_method = session.post if method.upper() == "POST" else session.get

            async with request_method(
                url,
                params=params,
                headers=self.auth_headers,
                ssl=ssl_context,
            ) as response:
                if return_json:
                    if response.status < 400:
                        return await response.json()
                    _LOGGER.error(
                        "API request to %s failed with status %s",
                        endpoint,
                        response.status,
                    )
                    return {}
                return response.status < 400
        except Exception as e:
            _LOGGER.error("API request to %s failed: %s", endpoint, e)
            return {} if return_json else False

    async def get_status(self) -> dict[str, Any]:
        """Fetch current track information."""
        result = await self.make_request(
            "mediaplayer/status", method="GET", return_json=True
        )
        if isinstance(result, dict):
            return result
        return {}

    async def play(self) -> bool:
        """Send play command."""
        result = await self.make_request("mediaplayer/play")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def pause(self) -> bool:
        """Send pause command."""
        result = await self.make_request("mediaplayer/play_pause")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def stop(self) -> bool:
        """Send stop command."""
        result = await self.make_request("mediaplayer/stop")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def next_track(self) -> bool:
        """Send next track command."""
        result = await self.make_request("mediaplayer/next_track")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def previous_track(self) -> bool:
        """Send previous track command."""
        result = await self.make_request("mediaplayer/previous_track")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def volume_up(self) -> bool:
        """Volume up the media player."""
        result = await self.make_request("mediaplayer/volume_up")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def volume_down(self) -> bool:
        """Volume down the media player."""
        result = await self.make_request("mediaplayer/volume_down")
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def set_volume(self, volume: float) -> bool:
        """Set volume level (0.0-1.0, will be converted to 0-100)."""
        # Convert HA volume (0-1) to jukebox volume (0-100)
        jukebox_volume = int(volume * 100)
        jukebox_volume = max(0, min(100, jukebox_volume))  # Clamp to valid range

        result = await self.make_request(
            "mediaplayer/volume_set",
            method="POST",
            params={"volume": jukebox_volume},
        )
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def play_album(
        self, album_id: str, start_track_index: int | None = None
    ) -> bool:
        """Play an album by its ID, optionally starting at a specific track."""
        params = (
            {"start_track_index": start_track_index}
            if start_track_index is not None
            else None
        )
        result = await self.make_request(
            f"mediaplayer/play_album_from_albumid/{album_id}",
            method="POST",
            params=params,
        )
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def get_artists(self) -> list[dict[str, Any]]:
        """Get all artists."""
        result = await self.make_request(
            "subsonic/artists", method="GET", return_json=True
        )
        if isinstance(result, list):
            return result
        return []

    async def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        """Get albums for a specific artist."""
        result = await self.make_request(
            f"subsonic/artist/{artist_id}", method="GET", return_json=True
        )
        if isinstance(result, list):
            return result
        return []

    async def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        """Get tracks for a specific album."""
        result = await self.make_request(
            f"subsonic/album/{album_id}", method="GET", return_json=True
        )
        if isinstance(result, list):
            return result
        return []

    async def get_output_status(self) -> dict[str, Any]:
        """Get output status including active backend/device and backend status."""
        result = await self.make_request(
            "output/status", method="GET", return_json=True
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_output_devices(self) -> list[dict[str, Any]]:
        """Get all available output devices."""
        result = await self.make_request(
            "output/devices", method="GET", return_json=True
        )
        if isinstance(result, dict) and "devices" in result:
            return result["devices"]
        return []

    async def switch_output_device(self, backend: str, device_name: str) -> bool:
        """Switch to a different output device/backend."""
        result = await self.make_request(
            "output/switch",
            method="POST",
            params={"backend": backend, "device_name": device_name},
        )
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def toggle_repeat_album(self) -> bool:
        """Toggle repeat album mode."""
        result = await self.make_request(
            "mediaplayer/toggle_repeat_album",
            method="POST",
        )
        return bool(result) if not isinstance(result, (dict, list)) else False

    async def toggle_mute(self) -> dict[str, Any] | None:
        """Toggle volume mute."""
        result = await self.make_request(
            "mediaplayer/volume_mute",
            method="POST",
            return_json=True,
        )
        # Return the full response dict so we can read the muted status
        return result if isinstance(result, dict) else None
