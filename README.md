# Jukeplayer Home Assistant Integration

Custom component for Home Assistant to control Jukeplayer.

## Features

- Display current track playing in Home Assistant
- Control playback (play/pause, next, previous)
- Show album art
- Volume control
- Integration with Home Assistant automations

## Installation

### Option 1: HACS (recommended)

1. Add this repo to HACS as custom repository
2. Install "Jukeplayer"
3. Restart Home Assistant
4. Add integration in Settings → Devices & Services

### Option 2: Manual

1. Copy `custom_components/jukeplayer/` to `<config>/custom_components/`
2. Restart Home Assistant
3. Add integration in Settings → Devices & Services

## Configuration

During integration setup, provide:
- Backend URL: `http://192.168.1.100:8000`
- Device name (optional)

## Entities

After installation, you'll get:

### Media Player
- `media_player.jukeplayer` - Main playback control

### Sensors
- `sensor.jukeplayer_current_track` - Current track name
- `sensor.jukeplayer_current_artist` - Current artist
- `sensor.jukeplayer_current_album` - Current album
- `sensor.jukeplayer_volume` - Current volume

### Services

Access via Developer Services or automations:
- `jukeplayer.next_track`
- `jukeplayer.previous_track`
- `jukeplayer.play_pause`

## Development

This is a placeholder for now. You will copy your existing Home Assistant code here.
