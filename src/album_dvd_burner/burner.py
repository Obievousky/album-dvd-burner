from pathlib import Path

from .config import Settings
from .utils import run


def burn_iso(iso_path: Path, settings: Settings, *, eject_after_burn: bool = False) -> None:
    device = settings.dvd_device
    if not Path(device).exists():
        raise FileNotFoundError(
            f"DVD device not found: {device}. "
            "Pass --device or set DVD_DEVICE, and mount the drive into the container."
        )

    cmd = [
        "xorriso",
        "-as",
        "cdrecord",
        "-v",
        f"dev={device}",
        "-blank",
        "as_needed",
    ]
    if eject_after_burn:
        cmd.append("-eject")
    cmd.append(str(iso_path))

    # xorriso replaces the old growisofs/genisoimage mix: it both creates valid
    # DVD-Video ISO layouts and burns to a DVD writer reliably.
    run(cmd)
