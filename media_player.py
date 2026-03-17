"""Jukebox media player integration."""

from __future__ import annotations

import base64
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from . import JukeboxConfigEntry
from .api_client import JukeboxAPIClient
from .browse_media import JukeboxBrowseMedia
from .websocket_handler import JukeboxWebSocket

_LOGGER = logging.getLogger(__name__)

# Configuration constants
CONF_USE_SSL = "use_ssl"
CONF_PORT = "port"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JukeboxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jukebox media player from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    use_ssl = entry.data.get(CONF_USE_SSL, True)
    port = entry.data.get(CONF_PORT, 443 if use_ssl else 80)

    # Create the media player entity
    entity = JukeboxMediaPlayer(
        entry=entry,
        host=host,
        port=port,
        username=username,
        password=password,
        use_ssl=use_ssl,
    )
    async_add_entities([entity], update_before_add=True)


class JukeboxMediaPlayer(MediaPlayerEntity):
    """Representation of a Jukebox Media Player."""

    def __init__(
        self,
        entry: ConfigEntry,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool,
    ) -> None:
        """Initialize the Jukebox Media Player."""
        self._entry = entry
        self._host = host
        self._port = port
        self._use_ssl = use_ssl
        self._attr_name = f"Jukebox {host}"
        self._attr_state = MediaPlayerState.IDLE
        self._track_info = {}
        self._attr_volume_level = None
        self._attr_is_volume_muted = False

        # Media position tracking
        self._attr_media_position = None
        self._attr_media_position_updated_at = None

        # Source selection (Chromecast devices)
        self._attr_source = None
        self._attr_source_list = []

        # Repeat mode
        self._attr_repeat = RepeatMode.OFF

        # Prepare basic auth headers for NPM
        auth_headers = {}
        if username and password:
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            auth_headers["Authorization"] = f"Basic {credentials}"
            _LOGGER.debug("Using basic authentication (NPM will inject API key)")
        else:
            _LOGGER.error("Username and password are required for NPM basic auth")

        # Build WebSocket URL
        protocol = "https" if use_ssl else "http"
        ws_protocol = "wss" if use_ssl else "ws"
        if (protocol == "https" and port == 443) or (protocol == "http" and port == 80):
            ws_url = f"{ws_protocol}://{host}/ws/mediaplayer/status"
        else:
            ws_url = f"{ws_protocol}://{host}:{port}/ws/mediaplayer/status"

        # Initialize helper modules
        self._api_client = JukeboxAPIClient(
            hass=None,  # Will be set in async_added_to_hass
            host=host,
            port=port,
            use_ssl=use_ssl,
            auth_headers=auth_headers,
        )
        self._ws_url = ws_url
        self._auth_headers = auth_headers

        self._browse_media_helper = JukeboxBrowseMedia(
            api_client=self._api_client,
            host=host,
            port=port,
            use_ssl=use_ssl,
        )

        self._websocket_handler: JukeboxWebSocket | None = None

    @property
    def unique_id(self) -> str:
        """Return unique ID for this entity."""
        return f"{self._entry.entry_id}_media_player"

    @property
    def should_poll(self) -> bool:
        """Return False as we use websockets for real-time updates."""
        return False

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        return self._track_info.get("title")

    @property
    def media_artist(self) -> str | None:
        """Artist of current playing media."""
        return self._track_info.get("artist")

    @property
    def media_album_name(self) -> str | None:
        """Album name of current playing media."""
        return self._track_info.get("album")

    @property
    def media_track(self) -> int | None:
        """Track number of current playing media."""
        return self._track_info.get("track_number")

    @property
    def media_duration(self) -> int | None:
        """Duration of current playing media in seconds."""
        duration_str = self._track_info.get("duration")
        if duration_str:
            try:
                # Convert MM:SS or HH:MM:SS to seconds
                parts = duration_str.split(":")
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            except (ValueError, TypeError):
                pass
        return None

    @property
    def media_position(self) -> int | None:
        """Position of current playing media in seconds."""
        return self._attr_media_position

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was last updated."""
        return self._attr_media_position_updated_at

    @property
    def media_image_url(self) -> str | None:
        """Image URL of current playing media."""
        # Try the new absolute thumb URL first
        thumb_abs = self._track_info.get("thumb_abs")
        if thumb_abs:
            # thumb_abs should already be a complete URL, return as-is
            _LOGGER.debug("Using thumb_abs: %s", thumb_abs)
            return thumb_abs

        _LOGGER.debug("No thumb image found in track info")
        return None

    @property
    def media_content_type(self) -> str | None:
        """Content type of current playing media."""
        # Return 'music' for audio tracks
        if self._track_info.get("title") or self._track_info.get("artist"):
            return "music"
        return None

    @property
    def media_content_id(self) -> str | None:
        """Content ID of current playing media."""
        # Use track_id if available, otherwise generate from title/artist
        track_id = self._track_info.get("track_id")
        if track_id:
            return str(track_id)

        # Fallback: create ID from title and artist
        title = self._track_info.get("title")
        artist = self._track_info.get("artist")
        if title and artist:
            return f"{artist}_{title}".replace(" ", "_").lower()
        if title:
            return title.replace(" ", "_").lower()
        return None

    @property
    def media_playlist(self) -> str | None:
        """Playlist name if track is part of a playlist."""
        return self._track_info.get("playlist_name") or self._track_info.get("playlist")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes for the media player."""
        attrs = {}

        # Add genre if available
        if self._track_info.get("genre"):
            attrs["genre"] = self._track_info.get("genre")

        # Add year if available
        if self._track_info.get("year"):
            attrs["year"] = self._track_info.get("year")

        # Add file format/codec if available
        if self._track_info.get("format") or self._track_info.get("codec"):
            attrs["format"] = self._track_info.get("format") or self._track_info.get(
                "codec"
            )

        # Add bitrate if available
        if self._track_info.get("bitrate"):
            attrs["bitrate"] = self._track_info.get("bitrate")

        # Add file path if available (useful for debugging)
        if self._track_info.get("file_path"):
            attrs["file_path"] = self._track_info.get("file_path")

        # Add playlist position if available
        if self._track_info.get("track_number"):
            attrs["playlist_position"] = self._track_info.get("track_number")

        # Add total tracks in playlist if available
        if self._track_info.get("playlist_total"):
            attrs["playlist_total"] = self._track_info.get("playlist_total")

        return attrs

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        return (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.REPEAT_SET
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        # Set hass on API client now that it's available
        self._api_client.hass = self.hass
        # Fetch initial source information
        try:
            await self._update_sources()
        except Exception as e:
            _LOGGER.debug("Error fetching initial source information: %s", e)
        # Start websocket connection
        self._websocket_handler = JukeboxWebSocket(
            hass=self.hass,
            ws_url=self._ws_url,
            auth_headers=self._auth_headers,
            use_ssl=self._port == 443 or self._use_ssl,
            data_callback=self._handle_websocket_message,
        )
        await self._websocket_handler.start()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        await super().async_will_remove_from_hass()
        # Close websocket connection
        if self._websocket_handler:
            await self._websocket_handler.stop()

    async def async_update(self) -> None:
        """Update the state of the media player."""
        # If websocket is connected, we get real-time updates and don't need to poll
        if self._websocket_handler and self._websocket_handler.is_connected:
            return

        # Prevent API calls if hass is not set yet
        if self._api_client.hass is None:
            _LOGGER.debug("Skipping async_update: HomeAssistant instance not set on API client")
            return

        # Fallback to polling if websocket isn't working
        try:
            data = await self._api_client.get_status()
            await self._update_from_data(data)
        except Exception as e:
            _LOGGER.error("Error updating Jukebox Media Player: %s", e)
            self._attr_state = MediaPlayerState.UNAVAILABLE

    async def _handle_websocket_message(self, data: dict[str, Any]) -> None:
        """Handle incoming websocket messages.

        This callback is invoked by the websocket handler when valid data is received.
        """
        await self._update_from_data(data)

    async def _update_from_data(self, data: dict[str, Any]) -> None:
        """Update entity state from websocket or API data."""
        try:
            # Handle jukebox data structure from websocket or API
            if "status" in data:
                status = data["status"]
                if status in ["PLAY", "playing"]:
                    self._attr_state = MediaPlayerState.PLAYING
                elif status in ["PAUSE", "paused"]:
                    self._attr_state = MediaPlayerState.PAUSED
                elif status in ["STOP", "idle", "STOP"]:
                    self._attr_state = MediaPlayerState.IDLE
                else:
                    self._attr_state = MediaPlayerState.IDLE

            # Handle current track info
            if data.get("current_track"):
                self._track_info = data["current_track"]
            else:
                self._track_info = {}

            # Update volume information from jukebox context (0-100 range)
            if "volume" in data:
                volume = data["volume"]
                if volume is not None:
                    # Convert jukebox volume (0-100) to HA volume (0-1)
                    old_volume = self._attr_volume_level
                    self._attr_volume_level = volume / 100.0
                    _LOGGER.debug(
                        "🔊 VOLUME UPDATE: %s (0-100) → %s (0-1), changed from %s",
                        volume,
                        self._attr_volume_level,
                        old_volume,
                    )
                else:
                    _LOGGER.debug("🔊 VOLUME: Received None volume")
            else:
                _LOGGER.debug("🔊 VOLUME: No volume data found in websocket message")

            # Update media position if available (from track timer)
            if "elapsed_time" in data:
                self._attr_media_position = int(data["elapsed_time"])
                self._attr_media_position_updated_at = utcnow()

            # Update repeat mode if available
            if "repeat_album" in data:
                # API returns a list with a single boolean value
                repeat_album = data["repeat_album"]
                if isinstance(repeat_album, list) and repeat_album:
                    self._attr_repeat = (
                        RepeatMode.ALL if repeat_album[0] else RepeatMode.OFF
                    )
                elif isinstance(repeat_album, bool):
                    self._attr_repeat = (
                        RepeatMode.ALL if repeat_album else RepeatMode.OFF
                    )

            # Update mute status if available
            if "muted" in data:
                self._attr_is_volume_muted = bool(data["muted"])

            # Schedule entity update
            if self.hass and self.entity_id:
                self.async_schedule_update_ha_state()
            else:
                _LOGGER.debug("Entity not fully registered yet, skipping state update")

        except Exception as e:
            _LOGGER.error("Error updating from data: %s", e)

        # Also update source information (Chromecast devices)
        # Do this separately to avoid blocking track updates
        try:
            await self._update_sources()
        except Exception as e:
            _LOGGER.debug("Error updating source information: %s", e)

    async def async_media_play(self) -> None:
        """Send play command."""
        await self._api_client.play()

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self._api_client.pause()

    async def async_media_stop(self) -> None:
        """Send stop command."""
        await self._api_client.stop()

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        await self._api_client.next_track()

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        await self._api_client.previous_track()

    async def async_volume_up(self) -> None:
        """Volume up the media player."""
        await self._api_client.volume_up()

    async def async_volume_down(self) -> None:
        """Volume down the media player."""
        await self._api_client.volume_down()

    async def async_select_source(self, source: str) -> None:
        """Select playback source (output device)."""
        # Find backend for the selected device
        devices = await self._api_client.get_output_devices()
        backend = None
        for device in devices:
            if device.get("name") == source:
                backend = device.get("backend")
                break
        if not backend:
            _LOGGER.error("Could not find backend for source: %s", source)
            return
        success = await self._api_client.switch_output_device(backend, source)
        if success:
            _LOGGER.debug(
                "Successfully switched to source: %s (backend: %s)", source, backend
            )
            self._attr_source = source
            self.async_schedule_update_ha_state()
            await self._update_sources()
        else:
            _LOGGER.error(
                "Failed to switch to source: %s (backend: %s)", source, backend
            )

    async def _update_sources(self) -> None:
        """Update available sources and active source from output status and devices."""
        # Get available devices
        devices = await self._api_client.get_output_devices()
        self._attr_source_list = [
            device.get("name") for device in devices if device.get("name")
        ]

        # Get active device from output status
        status = await self._api_client.get_output_status()
        active_device = status.get("active_device")
        if active_device:
            self._attr_source = active_device

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play media from browse media."""
        _LOGGER.debug("Play media called: type=%s, id=%s", media_type, media_id)

        # Parse the media_id to determine what to play
        # Format: "album:{album_id}" or "track:{album_id}:{track_index}"
        if media_id.startswith("album:"):
            album_id = media_id.split(":", 1)[1]
            await self._api_client.play_album(album_id)
        elif media_id.startswith("track:"):
            # Format: "track:{album_id}:{track_index}"
            parts = media_id.split(":", 2)
            if len(parts) == 3:
                album_id = parts[1]
                track_index = int(parts[2])
                await self._api_client.play_album(album_id, track_index)
            else:
                _LOGGER.error("Invalid track media_id format: %s", media_id)
        else:
            _LOGGER.warning("Unknown media_id format: %s", media_id)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        success = await self._api_client.set_volume(volume)

        if success:
            # Update local volume level immediately for responsive UI
            self._attr_volume_level = volume
            self.async_schedule_update_ha_state()
        else:
            _LOGGER.error("Failed to set volume to %s", volume)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode."""
        _LOGGER.debug(
            "Setting repeat mode to: %s (current: %s)", repeat, self._attr_repeat
        )

        # The API only supports toggling album repeat
        # When HA cycles through modes (OFF → ALL → ONE → OFF), we toggle when needed
        # Map RepeatMode.ONE to RepeatMode.ALL since we only have album repeat

        # Call the toggle API
        success = await self._api_client.toggle_repeat_album()
        if success:
            _LOGGER.debug("Successfully toggled repeat mode")
            # Update local state immediately for responsive UI
            # Map ONE to ALL since API only supports album repeat
            if repeat == RepeatMode.ONE:
                self._attr_repeat = RepeatMode.ALL
            else:
                self._attr_repeat = repeat
            self.async_schedule_update_ha_state()
        else:
            _LOGGER.error("Failed to toggle repeat mode")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute volume."""
        _LOGGER.debug(
            "Toggle mute called (requested: %s, current: %s)",
            mute,
            self._attr_is_volume_muted,
        )

        # Call the toggle mute API
        result = await self._api_client.toggle_mute()
        if result:
            # Update local state from API response
            muted_status = result.get("muted", False)
            self._attr_is_volume_muted = muted_status
            _LOGGER.debug("Mute toggled successfully, new state: %s", muted_status)
            self.async_schedule_update_ha_state()
        else:
            _LOGGER.error("Failed to toggle mute")

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        _LOGGER.debug(
            "Browse media called with type=%s, id=%s",
            media_content_type,
            media_content_id,
        )

        # Root level - show letter groups
        if media_content_id is None:
            return await self._browse_media_helper.build_root()

        # Parse the media_content_id to determine what to show
        # Format: "letter_group:{start}-{end}" or "artist:{artist_id}" or "album:{album_id}"
        if media_content_id.startswith("letter_group:"):
            letter_range = media_content_id.split(":", 1)[1]
            start_letter, end_letter = letter_range.split("-", 1)
            return await self._browse_media_helper.build_letter_group(
                start_letter, end_letter
            )
        if media_content_id.startswith("artist:"):
            artist_id = media_content_id.split(":", 1)[1]
            return await self._browse_media_helper.build_artist_albums(artist_id)
        if media_content_id.startswith("album:"):
            album_id = media_content_id.split(":", 1)[1]
            return await self._browse_media_helper.build_album_tracks(album_id)

        # Fallback to root
        return await self._browse_media_helper.build_root()
