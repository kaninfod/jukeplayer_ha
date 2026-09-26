# Jukeplayer — Home Assistant Integration

Custom Home Assistant integration for the [Jukeplayer backend](https://github.com/kaninfod/jukeplayer_backend):
real-time media player state and full control of the jukebox.

## Features

- Real-time state over the backend's WebSocket: track, artist, album, position, volume, mute, repeat
- Transport controls (play/pause, stop, next/previous) and volume — over the WebSocket, HTTP only as fallback
- Browse media: artists → albums → tracks straight from the Subsonic library, with cover art
- Source selection: switch playback between the backend's configured speakers
- Album art in the media player and browse cards

## Installation

### Option 1: HACS (recommended)

This repo ships the integration under `custom_components/jukebox_media_player/`
and is HACS-compatible:

1. In **HACS → ⋮ → Custom repositories**, add `https://github.com/kaninfod/jukeplayer_ha`
   with category **Integration**
2. Install **Jukeplayer**
3. Restart Home Assistant
4. Add the integration in **Settings → Devices & Services → Add Integration → Jukebox Mediaplayer**

### Option 2: Manual

1. Copy `custom_components/jukebox_media_player/` into `<config>/custom_components/`
2. Restart Home Assistant
3. Add the integration as above

## Configuration

- **Host**: the backend's address. A plain IP is the most reliable choice —
  Home Assistant resolves DNS with its own resolver (no search-suffix
  fallback), so short hostnames like `jukeplayer-rpi` often fail where
  `jukeplayer-rpi.lan` or the IP works.
- **Port**: the backend's HTTP port (default `8000`; use `80` when the
  backend serves on the default HTTP port — the port is then omitted from
  URLs).

There is no TLS option: the backend is LAN-only plain HTTP by design.

## Notes

- The integration registers a `home_assistant` client on the backend's
  **default speaker** and receives real-time updates over
  `ws://<host>[:port]/ws/mediaplayer/events`.
- Existing (version 1) config entries migrate automatically on upgrade —
  the legacy `use_ssl` option is dropped and the stored port is kept.
- Backend compatibility: requires the `feature/config-management` backend
  (speaker broker + `/api/output/*` + `/ws/mediaplayer/events`).