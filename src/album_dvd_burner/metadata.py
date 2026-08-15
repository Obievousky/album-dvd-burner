from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .utils import list_audio_files, run_capture
from .workspaces import sanitize_name


@dataclass(frozen=True)
class AlbumTags:
    artist: str | None
    album: str | None

    @property
    def display_name(self) -> str | None:
        artist = self.artist.strip() if self.artist else None
        album = self.album.strip() if self.album else None
        if artist and album:
            if album.lower().startswith(artist.lower()):
                return album
            return f"{artist} - {album}"
        return album or artist


def probe_tags(path: Path) -> dict[str, str]:
    output = run_capture(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(path),
        ]
    )
    data = json.loads(output)
    raw = data.get("format", {}).get("tags", {})
    return {key.lower(): str(value).strip() for key, value in raw.items() if str(value).strip()}


def _artist_from_tags(tags: dict[str, str]) -> str | None:
    for key in ("album_artist", "albumartist", "band", "artist"):
        value = tags.get(key)
        if value:
            return value
    return None


def _album_from_tags(tags: dict[str, str]) -> str | None:
    return tags.get("album")


def tags_from_file(path: Path) -> AlbumTags:
    tags = probe_tags(path)
    return AlbumTags(artist=_artist_from_tags(tags), album=_album_from_tags(tags))


def _most_common(values: list[str]) -> str | None:
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def detect_album_tags(folder: Path) -> AlbumTags:
    tracks = list_audio_files(folder, recursive=True)
    if not tracks:
        return AlbumTags(artist=None, album=None)

    artists: list[str] = []
    albums: list[str] = []
    for track in tracks:
        tags = tags_from_file(track)
        if tags.artist:
            artists.append(tags.artist)
        if tags.album:
            albums.append(tags.album)

    return AlbumTags(
        artist=_most_common(artists),
        album=_most_common(albums),
    )


def format_album_name(tags: AlbumTags, fallback: str | None = None) -> tuple[str, str]:
    """Return (workspace name, detection source)."""
    if tags.display_name:
        return sanitize_name(tags.display_name), "tags"

    if fallback:
        return sanitize_name(fallback), "fallback"

    raise ValueError("Could not detect album name from audio tags; provide a name override.")


def unique_workspace_name(data_root: Path, base_name: str) -> str:
    name = sanitize_name(base_name)
    if not (data_root / name).exists():
        return name

    for index in range(2, 100):
        candidate = sanitize_name(f"{base_name} ({index})")
        if not (data_root / candidate).exists():
            return candidate

    raise ValueError(f"Too many folders named like {base_name}")


def resolve_workspace_name(
    data_root: Path,
    source_dir: Path,
    *,
    override: str | None = None,
    fallback: str | None = None,
) -> tuple[str, str]:
    if override:
        return unique_workspace_name(data_root, override), "override"

    tags = detect_album_tags(source_dir)
    base_name, source = format_album_name(tags, fallback=fallback)
    return unique_workspace_name(data_root, base_name), source
