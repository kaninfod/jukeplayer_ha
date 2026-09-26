"""API client for the Jukeplayer backend (plain HTTP, LAN-only)."""

from __future__ import annotations

import logging
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
    ) -> None:
        """Initialize the API client.

        The backend is LAN-only plain HTTP by design; the port is omitted
        from URLs when it is the default for the scheme (80).
        """
        self.hass: HomeAssistant | None = hass
        self.host = host
        self.port = port

        if port == 80:
            self.api_base = f"http://{host}/api"
        else:
            self.api_base = f"http://{host}:{port}/api"

    async def make_request(
        self,
        endpoint: str,
        method: str = "POST",
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        return_json: bool = False,
    ) -> bool | dict[str, Any] | list[Any]:
        """Make a request to the Jukebox API.

        Args:
            endpoint: API endpoint (e.g. "mediaplayer/status")
            method: HTTP method ("GET" or "POST")
            params: Query parameters to include in the request
            json: JSON body for POST requests
            return_json: If True, return the JSON response; otherwise return success bool

        Returns:
            If return_json is True: dict/list with the JSON response.
                - Transport failures (DNS, refused, timeout) are RE-RAISED so
                  callers can distinguish "backend down" from "empty answer"
                  (the entity's polling fallback marks itself UNAVAILABLE).
            If return_json is False: bool indicating success (status < 400).
        """
        try:
            if not self.hass:
                _LOGGER.error("HomeAssistant instance not set on API client")
                return {} if return_json else False

            session = async_get_clientsession(self.hass)
            url = f"{self.api_base}/{endpoint}"
            request_method = session.post if method.upper() == "POST" else session.get

            async with request_method(url, params=params, json=json) as response:
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
            if return_json:
                # Transport failure — let callers decide (e.g. the entity
                # marks itself UNAVAILABLE instead of silently freezing).
                _LOGGER.error("API request to %s failed: %s", endpoint, e)
                raise
            _LOGGER.error("API request to %s failed: %s", endpoint, e)
            return False

    async def get_default_speaker(self) -> str | None:
        """The backend's default speaker — used to register the WS client so
        it lands on a speaker and receives current_track broadcasts.

        Reads it from /api/output/speakers (default_speaker field, backend
        api-v2 and later); falls back to the legacy /api/output/options for
        older backends."""
        try:
            result = await self.make_request(
                "output/speakers", method="GET", return_json=True
            )
        except Exception as e:
            _LOGGER.debug("Could not fetch speakers for default lookup: %s", e)
            return None
        if isinstance(result, dict) and result.get("default_speaker"):
            return result["default_speaker"]

        # legacy backend: /options still carried the default
        try:
            legacy = await self.make_request(
                "output/options", method="GET", return_json=True
            )
        except Exception as e:
            _LOGGER.debug("Could not fetch default speaker: %s", e)
            return None
        if isinstance(legacy, dict):
            return (legacy.get("defaults") or {}).get("speaker")
        return None

    async def get_status(self) -> dict[str, Any]:
        """Fetch current track information."""
        result = await self.make_request(
            "mediaplayer/status", method="GET", return_json=True
        )
        if isinstance(result, dict):
            return result
        return {}

    async def play_pause(self) -> bool:
        """Send play/pause command."""
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

    async def get_output_devices(self) -> list[dict[str, Any]]:
        """Get all available output devices from /api/output/speakers."""
        result = await self.make_request(
            "output/speakers", method="GET", return_json=True
        )

        if isinstance(result, dict) and "devices" in result:
            mapped_devices = []
            for speaker, details in result["devices"].items():
                raw_name = details.get("speaker_name", "")
                backend = details.get("backend", "")
                _LOGGER.debug(
                    "Mapping output device: raw_name=%s, backend=%s for speaker=%s",
                    raw_name,
                    backend,
                    speaker,
                )
                mapped_devices.append(
                    {
                        "backend": backend,
                        "device": raw_name,
                        "name": details.get("display_name") or raw_name,
                    }
                )
            return mapped_devices

        return []

    async def switch_output_device(self, device_name: str, client_id: str) -> bool:
        """Switch to a different output device/backend.

        Legacy HTTP path (the backend endpoint was removed with the client
        registry); source switching goes over the WebSocket (switch_device).
        """
        result = await self.make_request(
            f"mediaplayer/instances/{device_name}/control",
            method="POST",
            json={"client_id": client_id},
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