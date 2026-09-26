"""The Jukebox Mediaplayer integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]

type JukeboxConfigEntry = ConfigEntry[dict[str, str]]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: JukeboxConfigEntry) -> bool:
    """Set up Jukebox Mediaplayer from a config entry."""
    # Store config data in runtime_data for platform access
    entry.runtime_data = dict(entry.data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    Version 1 entries carried a `use_ssl` key (from the era when a TLS
    proxy could front the backend). The backend is LAN-only plain HTTP by
    design — drop the key; the stored port is kept as-is.
    """
    if entry.version > 2:
        # Downgrade from a future version is not supported
        return False

    if entry.version == 1:
        new_data = {k: v for k, v in entry.data.items() if k != "use_ssl"}
        hass.config_entries.async_update_entry(
            entry, data=new_data, version=2, minor_version=1
        )
        _LOGGER.info("Migrated Jukebox config entry to version 2 (use_ssl removed)")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: JukeboxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
