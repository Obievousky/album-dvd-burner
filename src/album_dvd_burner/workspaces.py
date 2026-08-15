from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

JOBS_DIR = "_jobs"
OUTPUT_DIRNAME = "output"
SOURCE_DIRNAME = "source"
PROCESSED_ARTWORK = "artwork_720x480.jpg"
CONVERTED_DIRNAME = "16-48"
CONVERTED_DIR_LABEL = "16/48"


def converted_dir(workspace: Path) -> Path:
    return workspace / CONVERTED_DIRNAME


@dataclass(frozen=True)
class RetentionOptions:
    """What to keep on disk after a successful job."""

    persistent: bool = True
    keep_source: bool = True
    keep_converted: bool = False
    keep_artwork: bool = True
    keep_iso: bool = True
    keep_video_ts: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "RetentionOptions":
        if not data:
            return cls()
        return cls(
            persistent=data.get("persistent", True),
            keep_source=data.get("keep_source", True),
            keep_converted=data.get("keep_converted", False),
            keep_artwork=data.get("keep_artwork", True),
            keep_iso=data.get("keep_iso", True),
            keep_video_ts=data.get("keep_video_ts", False),
        )

    def to_dict(self) -> dict:
        return {
            "persistent": self.persistent,
            "keep_source": self.keep_source,
            "keep_converted": self.keep_converted,
            "keep_artwork": self.keep_artwork,
            "keep_iso": self.keep_iso,
            "keep_video_ts": self.keep_video_ts,
        }


def safe_resolve_under(base: Path, relative: str) -> Path:
    base = base.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path escapes base directory: {relative!r}")
    return target


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        raise ValueError("Album name cannot be empty")
    if cleaned in {JOBS_DIR, OUTPUT_DIRNAME, SOURCE_DIRNAME, CONVERTED_DIRNAME}:
        raise ValueError(f"Reserved name: {cleaned}")
    return cleaned


def album_workspace(data_root: Path, name: str) -> Path:
    return data_root / sanitize_name(name)


def album_source_dir(workspace: Path) -> Path:
    source = workspace / SOURCE_DIRNAME
    if source.is_dir():
        return source
    return workspace


def job_output_dir(data_root: Path, burn_code: str, album_names: list[str]) -> Path:
    if len(album_names) == 1:
        return album_workspace(data_root, album_names[0]) / OUTPUT_DIRNAME
    safe_code = sanitize_name(burn_code)
    return data_root / JOBS_DIR / safe_code / OUTPUT_DIRNAME


def is_album_workspace(path: Path, data_root: Path) -> bool:
    if not path.is_dir() or path.name.startswith("."):
        return False
    if path.name == JOBS_DIR:
        return False
    if path.resolve() == data_root.resolve():
        return False
    return True


def list_album_workspaces(data_root: Path) -> list[Path]:
    if not data_root.exists():
        return []
    return sorted(
        path
        for path in data_root.iterdir()
        if is_album_workspace(path, data_root)
    )
