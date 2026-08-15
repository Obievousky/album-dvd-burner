from __future__ import annotations

import shutil
from pathlib import Path

from .retention_scheduler import retention_scheduler
from .workspaces import JOBS_DIR, PROCESSED_ARTWORK, SOURCE_DIRNAME, RetentionOptions, converted_dir


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    current = path.resolve()
    stop = stop_at.resolve()
    while current != stop and current.is_dir() and current.exists():
        if any(current.iterdir()):
            break
        parent = current.parent
        current.rmdir()
        current = parent


def _delete_or_schedule(
    path: Path,
    *,
    label: str,
    delay_hours: float,
    burn_code: str | None,
    job_id: str | None,
) -> str | None:
    if not path.exists():
        return None

    if delay_hours > 0:
        return retention_scheduler.schedule(
            path,
            label=label,
            burn_code=burn_code,
            job_id=job_id,
            delay_hours=delay_hours,
        )

    if _remove_path(path):
        return f"Removed {label}: {path}"
    return None


def apply_retention(
    data_root: Path,
    album_workspaces: list[Path],
    output_dir: Path,
    options: RetentionOptions,
    *,
    delay_hours: float = 3.0,
    burn_code: str | None = None,
    job_id: str | None = None,
) -> list[str]:
    messages: list[str] = []

    if not options.persistent:
        options = RetentionOptions(
            persistent=False,
            keep_source=False,
            keep_converted=False,
            keep_artwork=False,
            keep_iso=False,
            keep_video_ts=False,
        )

    if options.persistent and all(
        [
            options.keep_source,
            options.keep_converted,
            options.keep_artwork,
            options.keep_iso,
            options.keep_video_ts,
        ]
    ):
        messages.append("Retention: keeping all files.")
        return messages

    if delay_hours > 0:
        retention_scheduler.configure(data_root, delay_hours=delay_hours)

    if delay_hours > 0:
        messages.append(
            f"Retention: unselected files will be deleted after {delay_hours:g} hour(s)."
        )
    elif not options.persistent:
        messages.append("Retention: non-persistent — removing generated files now.")
    else:
        messages.append("Retention: removing unselected file types now.")

    iso_path = output_dir / "disc.iso"
    if not options.keep_iso:
        message = _delete_or_schedule(
            iso_path,
            label="ISO",
            delay_hours=delay_hours,
            burn_code=burn_code,
            job_id=job_id,
        )
        if message:
            messages.append(message)

    for dirname in ("VIDEO_TS", "AUDIO_TS"):
        target = output_dir / dirname
        if not options.keep_video_ts:
            message = _delete_or_schedule(
                target,
                label=dirname,
                delay_hours=delay_hours,
                burn_code=burn_code,
                job_id=job_id,
            )
            if message:
                messages.append(message)

    for workspace in album_workspaces:
        converted = converted_dir(workspace)
        artwork = workspace / PROCESSED_ARTWORK
        source = workspace / SOURCE_DIRNAME

        if not options.keep_converted:
            message = _delete_or_schedule(
                converted,
                label="converted audio",
                delay_hours=delay_hours,
                burn_code=burn_code,
                job_id=job_id,
            )
            if message:
                messages.append(message)

        if not options.keep_artwork:
            message = _delete_or_schedule(
                artwork,
                label="artwork",
                delay_hours=delay_hours,
                burn_code=burn_code,
                job_id=job_id,
            )
            if message:
                messages.append(message)

        if not options.keep_source:
            message = _delete_or_schedule(
                source,
                label="source files",
                delay_hours=delay_hours,
                burn_code=burn_code,
                job_id=job_id,
            )
            if message:
                messages.append(message)

    if not options.persistent:
        message = _delete_or_schedule(
            output_dir,
            label="output directory",
            delay_hours=delay_hours,
            burn_code=burn_code,
            job_id=job_id,
        )
        if message:
            messages.append(message)
        elif delay_hours <= 0 and _remove_path(output_dir):
            messages.append(f"Removed output directory: {output_dir}")
            job_folder = output_dir.parent
            jobs_root = data_root / JOBS_DIR
            if job_folder.parent.resolve() == jobs_root.resolve():
                _prune_empty_parents(job_folder, jobs_root)
                _prune_empty_parents(jobs_root, data_root)

    return messages
