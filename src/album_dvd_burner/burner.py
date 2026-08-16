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

    # Try to detect whether a disc is present using the Linux CD-ROM ioctl.
    # If detection is unavailable or fails, assume media is present to avoid spurious tray operations.
    def _media_present(dev_path: str) -> bool:
        try:
            import fcntl
            CDS_NO_INFO = 0
            CDS_NO_DISC = 1
            CDS_TRAY_OPEN = 2
            CDS_DRIVE_NOT_READY = 3
            CDS_DISC_OK = 4
            with open(dev_path, "rb") as fd:
                status = fcntl.ioctl(fd, 0x5326, 0)
                return int(status) == CDS_DISC_OK
        except Exception:
            # If detection isn't supported, don't attempt to auto-eject — assume a disc is present
            return True

    if not _media_present(device):
        # Open the tray so the user can insert a disc
        try:
            run(["eject", device])
        except Exception:
            # If eject isn't available or fails, raise a clear error
            raise RuntimeError(
                f"No disc present in {device} and the tray could not be opened automatically."
            )
        # Notify caller that user action is required
        raise RuntimeError(f"No disc present in {device}. Tray opened — insert disc and retry the job.")

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
