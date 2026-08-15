from pathlib import Path

from .config import Settings
from .utils import run


def burn_iso(iso_path: Path, settings: Settings) -> None:
    device = settings.dvd_device
    if not Path(device).exists():
        raise FileNotFoundError(
            f"DVD device not found: {device}. "
            "Pass --device or set DVD_DEVICE, and mount the drive into the container."
        )

    run(
        [
            "growisofs",
            f"dev={device}",
            "-Z",
            f"{device}={iso_path}",
        ]
    )
