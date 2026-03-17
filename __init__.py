"""The Jukebox Mediaplayer integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]

type JukeboxConfigEntry = ConfigEntry[dict[str, str]]


async def async_setup_entry(hass: HomeAssistant, entry: JukeboxConfigEntry) -> bool:
    """Set up Jukebox Mediaplayer from a config entry."""
    # Store config data in runtime_data for platform access
    entry.runtime_data = dict(entry.data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: JukeboxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
