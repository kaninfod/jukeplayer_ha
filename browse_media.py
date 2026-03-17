"""Browse media functionality for Jukebox media player."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaType,
)

if TYPE_CHECKING:
    from .api_client import JukeboxAPIClient

_LOGGER = logging.getLogger(__name__)


class JukeboxBrowseMedia:
    """Handle browse media tree building for Jukebox."""

    def __init__(
        self,
        api_client: JukeboxAPIClient,
        host: str,
        port: int,
        use_ssl: bool,
    ) -> None:
        """Initialize the browse media handler."""
        self.api_client = api_client
        self.host = host
        self.port = port
        self.use_ssl = use_ssl

    def _build_absolute_url(self, relative_url: str) -> str | None:
        """Build absolute URL from relative path."""
        if not relative_url:
            return None

        if relative_url.startswith("http"):
            return relative_url

        # Build absolute URL using the same base as API
        protocol = "https" if self.use_ssl else "http"
        if (protocol == "https" and self.port == 443) or (
            protocol == "http" and self.port == 80
        ):
            return f"{protocol}://{self.host}{relative_url}"
        return f"{protocol}://{self.host}:{self.port}{relative_url}"

    async def build_root(self) -> BrowseMedia:
        """Browse root level - show letter groups."""
        # Define letter groups
        letter_groups = [
            ("A-D", "a", "d"),
            ("E-H", "e", "h"),
            ("I-L", "i", "l"),
            ("M-P", "m", "p"),
            ("Q-T", "q", "t"),
            ("U-X", "u", "x"),
            ("Y-Z", "y", "z"),
        ]

        children = []

        for group_title, start_letter, end_letter in letter_groups:
            children.append(
                BrowseMedia(
                    title=group_title,
                    media_class=MediaClass.DIRECTORY,
                    media_content_type="letter_group",
                    media_content_id=f"letter_group:{start_letter}-{end_letter}",
                    can_play=False,
                    can_expand=True,
                )
            )

        return BrowseMedia(
            title="Artists",
            media_class=MediaClass.DIRECTORY,
            media_content_type="library",
            media_content_id="root",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def build_letter_group(
        self, start_letter: str, end_letter: str
    ) -> BrowseMedia:
        """Browse letter group - show artists in letter range."""
        artists_data = await self.api_client.get_artists()

        # Filter artists by letter range
        children = []
        start_lower = start_letter.lower()
        end_lower = end_letter.lower()

        for artist in artists_data:
            artist_id = artist.get("id")
            artist_name = artist.get("name")

            if artist_id and artist_name:
                first_letter = artist_name[0].lower()
                # Check if first letter is in range (inclusive)
                if start_lower <= first_letter <= end_lower:
                    children.append(
                        BrowseMedia(
                            title=artist_name,
                            media_class=MediaClass.ARTIST,
                            media_content_type=MediaType.ARTIST,
                            media_content_id=f"artist:{artist_id}",
                            can_play=False,
                            can_expand=True,
                        )
                    )

        # Sort children by name
        children.sort(key=lambda x: x.title.lower())

        group_title = f"{start_letter.upper()}-{end_letter.upper()}"

        return BrowseMedia(
            title=f"Artists ({group_title})",
            media_class=MediaClass.DIRECTORY,
            media_content_type="letter_group",
            media_content_id=f"letter_group:{start_letter}-{end_letter}",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def build_artist_albums(self, artist_id: str) -> BrowseMedia:
        """Browse albums for a specific artist."""
        albums_data = await self.api_client.get_artist_albums(artist_id)

        # Build album list
        children = []

        for album in albums_data:
            album_id = album.get("id")
            album_name = album.get("name")
            album_year = album.get("year")
            cover_url = album.get("cover_url")

            # Build absolute URL for cover if available
            thumbnail = self._build_absolute_url(cover_url) if cover_url else None

            if album_id and album_name:
                title = f"{album_name} ({album_year})" if album_year else album_name
                children.append(
                    BrowseMedia(
                        title=title,
                        media_class=MediaClass.ALBUM,
                        media_content_type=MediaType.ALBUM,
                        media_content_id=f"album:{album_id}",
                        can_play=True,
                        can_expand=True,
                        thumbnail=thumbnail,
                    )
                )

        # Get artist name from first album or use ID as fallback
        artist_name = f"Artist {artist_id}"

        return BrowseMedia(
            title=f"{artist_name} - Albums",
            media_class=MediaClass.ARTIST,
            media_content_type=MediaType.ARTIST,
            media_content_id=f"artist:{artist_id}",
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def build_album_tracks(self, album_id: str) -> BrowseMedia:
        """Browse tracks for a specific album."""
        tracks_data = await self.api_client.get_album_tracks(album_id)

        # Build track list
        children = []
        album_name = None
        album_art_url = None

        for index, track in enumerate(tracks_data):
            track_id = track.get("id")
            track_title = track.get("title")
            track_artist = track.get("artist")
            track_number = track.get("track")
            album_id_from_track = track.get("albumId")
            cover_art = track.get("coverArt")

            # Get album name from first track
            if not album_name and track.get("album"):
                album_name = track.get("album")

            # Build cover art URL if available
            if not album_art_url and cover_art:
                protocol = "https" if self.use_ssl else "http"
                if (protocol == "https" and self.port == 443) or (
                    protocol == "http" and self.port == 80
                ):
                    album_art_url = f"{protocol}://{self.host}/assets/covers/{cover_art}/cover-180.webp"
                else:
                    album_art_url = f"{protocol}://{self.host}:{self.port}/assets/covers/{cover_art}/cover-180.webp"

            if track_id and track_title:
                # Format: track:{album_id}:{track_index}
                title = (
                    f"{track_number}. {track_title}" if track_number else track_title
                )
                if track_artist:
                    title = f"{title} - {track_artist}"

                children.append(
                    BrowseMedia(
                        title=title,
                        media_class=MediaClass.TRACK,
                        media_content_type=MediaType.TRACK,
                        media_content_id=f"track:{album_id_from_track or album_id}:{index}",
                        can_play=True,
                        can_expand=False,
                    )
                )

        album_name = album_name or f"Album {album_id}"

        return BrowseMedia(
            title=album_name,
            media_class=MediaClass.ALBUM,
            media_content_type=MediaType.ALBUM,
            media_content_id=f"album:{album_id}",
            can_play=True,
            can_expand=True,
            children=children,
            thumbnail=album_art_url,
        )
