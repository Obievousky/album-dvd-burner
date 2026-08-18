import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # Keep library helpers usable in minimal/test environments.
    def load_dotenv() -> bool:
        return False

load_dotenv()

AUDIO_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif"}
ARTWORK_NAMES = (
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "front.jpg",
    "front.jpeg",
    "front.png",
    "artwork.jpg",
    "artwork.jpeg",
    "artwork.png",
)


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    dvd_device: str
    dvd_standard: str
    data_root: Path
    burn_id_prefix: str
    web_api_key: str | None
    retention_delay_hours: float

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("WEB_API_KEY")
        data_root = Path(os.getenv("DATA_ROOT", os.getenv("INPUT_DIR", "./data")))
        try:
            postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
            retention_delay_hours = float(os.getenv("RETENTION_DELAY_HOURS", "3"))
        except ValueError as exc:
            raise ValueError("POSTGRES_PORT must be an integer and RETENTION_DELAY_HOURS a number") from exc

        dvd_standard = os.getenv("DVD_STANDARD", "ntsc").lower()
        if dvd_standard not in {"ntsc", "pal"}:
            raise ValueError("DVD_STANDARD must be 'ntsc' or 'pal'")
        if postgres_port <= 0 or postgres_port > 65535:
            raise ValueError("POSTGRES_PORT must be between 1 and 65535")
        if retention_delay_hours < 0:
            raise ValueError("RETENTION_DELAY_HOURS cannot be negative")

        return cls(
            postgres_host=os.getenv("POSTGRES_HOST", "localhost"),
            postgres_port=postgres_port,
            postgres_db=os.getenv("POSTGRES_DB", "album_dvd"),
            postgres_user=os.getenv("POSTGRES_USER", "album_dvd"),
            postgres_password=os.getenv("POSTGRES_PASSWORD", "album_dvd"),
            dvd_device=os.getenv("DVD_DEVICE", "/dev/sr0"),
            dvd_standard=dvd_standard,
            data_root=data_root,
            burn_id_prefix=os.getenv("BURN_ID_PREFIX", "R.P. No."),
            web_api_key=api_key if api_key else None,
            retention_delay_hours=retention_delay_hours,
        )

    @property
    def input_dir(self) -> Path:
        """Backward-compatible alias for album scan root."""
        return self.data_root

    @property
    def output_dir(self) -> Path:
        """Backward-compatible alias; per-job output is computed at runtime."""
        return self.data_root / "_jobs"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
