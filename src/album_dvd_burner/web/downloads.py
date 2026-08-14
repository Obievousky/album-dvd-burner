from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from datetime import datetime

from fastapi import BackgroundTasks
from fastapi.responses import FileResponse, Response

from ..jobs import Job


def _format_seconds(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {sec}s"


def format_job_log(job: Job) -> str:
    lines = [
        f"Job ID: {job.id}",
        f"Status: {job.status.value}",
        f"Albums: {', '.join(job.album_names)}",
    ]
    if job.burn_code:
        lines.append(f"Burn code: {job.burn_code}")
    if job.output_dir:
        lines.append(f"Output directory: {job.output_dir}")
    if job.iso_path:
        lines.append(f"ISO path: {job.iso_path}")
    lines.append("")
    lines.extend(f"{log.timestamp} [{log.stage}] {log.message}" for log in job.logs)
    if job.error:
        lines.append(f"[error] {job.error}")

    # If we have start and finish timestamps, append total duration
    try:
        if job.started_at and job.finished_at:
            started = datetime.fromisoformat(job.started_at)
            finished = datetime.fromisoformat(job.finished_at)
            total_seconds = int((finished - started).total_seconds())
            lines.append("")
            lines.append(f"Total time: { _format_seconds(total_seconds) } ({total_seconds}s)")
    except Exception:
        # Do not fail logging if timestamp parsing fails
        pass

    return "\n".join(lines) + "\n"


def _dir_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _safe_filename(value: str) -> str:
    cleaned = value.replace("/", "-").replace("\\", "-").strip()
    return cleaned or "output"


def list_job_outputs(job: Job) -> list[dict]:
    if not job.output_dir:
        return []

    output_dir = Path(job.output_dir)
    if not output_dir.is_dir():
        return []

    outputs: list[dict] = []
    safe_name = _safe_filename(job.burn_code or job.id)

    iso_path = output_dir / "disc.iso"
    if iso_path.is_file():
        outputs.append(
            {
                "id": "disc.iso",
                "label": "disc.iso",
                "filename": f"{safe_name}-disc.iso",
                "size": iso_path.stat().st_size,
                "kind": "file",
                "download_url": f"/api/jobs/{job.id}/download/disc.iso",
            }
        )

    for folder_name in ("VIDEO_TS", "AUDIO_TS"):
        folder = output_dir / folder_name
        if folder.is_dir():
            outputs.append(
                {
                    "id": folder_name,
                    "label": f"{folder_name} (zip)",
                    "filename": f"{safe_name}-{folder_name}.zip",
                    "size": _dir_size(folder),
                    "kind": "archive",
                    "download_url": f"/api/jobs/{job.id}/download/{folder_name}",
                }
            )

    return outputs


def job_log_response(job: Job) -> Response:
    filename = f"{_safe_filename(job.burn_code or job.id)}-log.txt"
    return Response(
        content=format_job_log(job),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def job_artifact_response(
    job: Job,
    artifact_id: str,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    if not job.output_dir:
        raise FileNotFoundError("Job has no output directory")

    output_dir = Path(job.output_dir)
    safe_name = _safe_filename(job.burn_code or job.id)

    if artifact_id == "disc.iso":
        path = output_dir / "disc.iso"
        if not path.is_file():
            raise FileNotFoundError("ISO not found")
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{safe_name}-disc.iso",
        )

    if artifact_id in {"VIDEO_TS", "AUDIO_TS"}:
        folder = output_dir / artifact_id
        if not folder.is_dir():
            raise FileNotFoundError(f"{artifact_id} not found")

        temp_dir = Path(tempfile.mkdtemp())
        archive_base = temp_dir / artifact_id
        shutil.make_archive(str(archive_base), "zip", folder.parent, folder.name)
        zip_path = Path(f"{archive_base}.zip")

        def cleanup() -> None:
            shutil.rmtree(temp_dir, ignore_errors=True)

        background_tasks.add_task(cleanup)
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"{safe_name}-{artifact_id}.zip",
        )

    raise FileNotFoundError(f"Unknown artifact: {artifact_id}")
