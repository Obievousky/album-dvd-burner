from pathlib import Path
import os

from .config import Settings
from .utils import run


def burn_iso(iso_path: Path, settings: Settings, *, eject_after_burn: bool = False, wait_timeout: int = 300) -> None:
    """Burn an ISO to the configured device.

    If no media is present, wait up to wait_timeout seconds for the user to insert a disc.
    """
    import time

    device = settings.dvd_device
    device_path = Path(device)
    if not device_path.is_block_device() or not os.access(device_path, os.R_OK | os.W_OK):
        raise FileNotFoundError(
            f"DVD device is unavailable or not writable: {device}. "
            "Pass --device or set DVD_DEVICE, map the drive into the container, "
            "and add its group through DVD_GID."
        )

    def _media_present(dev_path: str) -> bool:
        try:
            import fcntl
            # CDROM_DRIVE_STATUS ioctl (CDROM_DRIVE_STATUS = 0x5326)
            CDROM_DRIVE_STATUS = 0x5326
            CDS_NO_INFO = 0
            CDS_NO_DISC = 1
            CDS_TRAY_OPEN = 2
            CDS_DRIVE_NOT_READY = 3
            CDS_DISC_OK = 4
            with open(dev_path, "rb") as fd:
                status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0)
                return int(status) == CDS_DISC_OK
        except Exception:
            # If detection isn't supported, assume media is present to avoid spurious tray operations
            return True

    # If no disc is present, attempt to open the tray (best-effort) and wait for insertion
    if not _media_present(device):
        try:
            run(["eject", device])
        except Exception:
            # ignore eject failures; we'll still wait for user to insert media
            pass

        start = time.time()
        while not _media_present(device):
            elapsed = time.time() - start
            if elapsed >= wait_timeout:
                raise RuntimeError(
                    f"No disc detected in {device} after waiting {wait_timeout} seconds."
                )
            time.sleep(5)

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
