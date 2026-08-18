from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .burner import burn_iso
from .config import Settings
from .database import BurnRecord, album_metadata, insert_burn, mark_burned, next_burn_code
from .dvd_author import author_dvd, prepare_album
from .progress import ProgressCallback, ProgressTracker
from .retention import apply_retention
from .workspaces import RetentionOptions, album_source_dir, job_output_dir


@dataclass
class ProcessResult:
    burn_code: str
    iso_path: Path
    output_dir: Path
    album_count: int
    burned: bool
    workspace_paths: list[Path]


def run_pipeline(
    album_folders: list[Path],
    settings: Settings,
    *,
    burn: bool = True,
    burn_code: str | None = None,
    job_id: str | None = None,
    retention: RetentionOptions | None = None,
    eject_after_burn: bool = False,
    on_progress: ProgressCallback | None = None,
) -> ProcessResult:
    workspaces = [path.resolve() for path in album_folders]
    if not workspaces:
        raise ValueError("At least one album folder is required")

    retention = retention or RetentionOptions()
    total_tracks = 0
    for workspace in workspaces:
        from .utils import list_audio_files

        total_tracks += len(list_audio_files(album_source_dir(workspace), recursive=True))

    total_steps = (
        len(workspaces) * 3
        + total_tracks
        + 5
        + (1 if burn else 0)
    )
    tracker = ProgressTracker(on_progress)
    tracker.set_stage("preparing", "Preparing albums", total=total_steps)

    code = burn_code or next_burn_code(settings)
    album_names = [workspace.name for workspace in workspaces]
    output_dir = job_output_dir(settings.data_root, code, album_names)

    tracker.log("preparing", f"Burn ID: {code}")
    tracker.log("preparing", f"Output directory: {output_dir}")
    tracker.advance("preparing", f"Preparing {len(workspaces)} album title(s)...")

    albums = []
    for workspace in workspaces:
        albums.append(prepare_album(workspace, tracker))
        tracker.advance("preparing", f"Album prepared: {workspace.name}", step=2)

    tracker.set_stage("authoring", "Authoring DVD", total=total_tracks + 2)
    iso_path = author_dvd(
        albums,
        output_dir,
        standard=settings.dvd_standard,
        tracker=tracker,
    )
    tracker.set("authoring", f"Authoring complete: {iso_path.name}", current=total_tracks + 2)

    tracker.set_stage("database", "Saving to database", total=1)
    insert_burn(
        settings,
        BurnRecord(
            burn_code=code,
            iso_path=str(iso_path),
            dvd_standard=settings.dvd_standard,
            albums=[album_metadata(album) for album in albums],
            metadata={
                "title_count": len(albums),
                "volume_label": code[:32],
                "output_dir": str(output_dir),
                "retention": retention.to_dict(),
            },
            dvd_device=settings.dvd_device if burn else None,
        ),
    )
    tracker.set("database", f"Database entry created: {code}", current=1)

    if burn:
        tracker.set_stage("burning", f"Burning to {settings.dvd_device}", total=1)
        burn_iso(iso_path, settings, eject_after_burn=eject_after_burn)
        mark_burned(settings, code)
        tracker.set("burning", "Burn complete.", current=1)
    else:
        tracker.log("done", "Skipping burn (ISO only).")

    tracker.set_stage("cleanup", "Applying retention rules", total=1)
    for message in apply_retention(
        settings.data_root,
        workspaces,
        output_dir,
        retention,
        delay_hours=settings.retention_delay_hours,
        burn_code=code,
        job_id=job_id,
    ):
        tracker.log("cleanup", message)
    tracker.set("cleanup", "Retention applied.", current=1)

    tracker.log("done", "Job finished.")
    return ProcessResult(
        burn_code=code,
        iso_path=iso_path,
        output_dir=output_dir,
        album_count=len(albums),
        burned=burn,
        workspace_paths=workspaces,
    )
