from __future__ import annotations

import io
import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..artwork import find_artwork
from ..audio import probe_audio
from ..config import Settings
from ..database import ensure_schema, list_burns, next_burn_code
from .. import __version__
from ..jobs import job_manager
from ..metadata import detect_album_tags, resolve_workspace_name
from ..retention_scheduler import retention_scheduler
from ..utils import list_audio_files
from ..workspaces import (
    SOURCE_DIRNAME,
    CONVERTED_DIR_LABEL,
    RetentionOptions,
    album_source_dir,
    album_workspace,
    converted_dir,
    list_album_workspaces,
    safe_resolve_under,
    sanitize_name,
)

from .downloads import job_artifact_response, job_log_response, list_job_outputs

STATIC_DIR = Path(__file__).parent / "static"

ALBUM_ORDER_FILENAME = ".album-order.json"


def _album_order_path(settings: Settings) -> Path:
    return settings.data_root / ALBUM_ORDER_FILENAME


def _load_album_order(settings: Settings) -> list[str]:
    path = _album_order_path(settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(name) for name in data]


def _save_album_order(settings: Settings, names: list[str]) -> None:
    _album_order_path(settings).write_text(json.dumps(names, indent=2), encoding="utf-8")


class RetentionRequest(BaseModel):
    persistent: bool = True
    keep_source: bool = True
    keep_converted: bool = False
    keep_artwork: bool = True
    keep_iso: bool = True
    keep_video_ts: bool = False


class RenameAlbumRequest(BaseModel):
    name: str = Field(min_length=1)


class OrderRequest(BaseModel):
    names: list[str] = Field(default_factory=list)


class CreateJobRequest(BaseModel):
    albums: list[str] = Field(min_length=1)
    burn: bool = True
    standard: str | None = None
    retention: RetentionRequest = Field(default_factory=RetentionRequest)
    eject_after_burn: bool = False


def get_settings() -> Settings:
    return Settings.from_env()


def verify_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    key: str | None = Query(default=None),
) -> None:
    provided = x_api_key or key
    if settings.web_api_key and provided != settings.web_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _resolve_workspace(settings: Settings, name: str) -> Path:
    try:
        workspace = album_workspace(settings.data_root, name).resolve()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    root = settings.data_root.resolve()
    if not workspace.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid album path")
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail=f"Album not found: {name}")
    return workspace


def _scan_album(workspace: Path) -> dict:
    source = album_source_dir(workspace)
    tracks = list_audio_files(source, recursive=True)
    if not tracks and source != workspace:
        tracks = list_audio_files(workspace, recursive=True)

    tags = detect_album_tags(source if tracks else workspace)
    has_artwork = find_artwork(workspace) is not None
    audio_info = None
    if tracks:
        info = probe_audio(tracks[0])
        audio_info = {
            "sample_rate": info.sample_rate,
            "bit_depth": info.bit_depth,
            "channels": info.channels,
        }

    converted = converted_dir(workspace).is_dir()
    has_output = (workspace / "output" / "disc.iso").exists()

    return {
        "name": workspace.name,
        "path": str(workspace),
        "artist": tags.artist,
        "album": tags.album,
        "track_count": len(tracks),
        "has_artwork": has_artwork,
        "converted": converted,
        "converted_label": CONVERTED_DIR_LABEL,
        "has_output": has_output,
        "audio_info": audio_info,
    }


def _staging_source_dir(settings: Settings) -> Path:
    staging = settings.data_root / f".staging-{uuid.uuid4().hex}"
    source = staging / SOURCE_DIRNAME
    source.mkdir(parents=True, exist_ok=True)
    return source


def _cleanup_staging(source_dir: Path) -> None:
    shutil.rmtree(source_dir.parent, ignore_errors=True)


def _require_staging_audio(source_dir: Path) -> None:
    if not list_audio_files(source_dir, recursive=True):
        _cleanup_staging(source_dir)
        raise HTTPException(status_code=400, detail="No audio files found in upload")


def _finalize_upload(
    settings: Settings,
    source_dir: Path,
    *,
    override: str | None = None,
    fallback: str | None = None,
) -> tuple[Path, str, str]:
    try:
        workspace_name, naming_source = resolve_workspace_name(
            settings.data_root,
            source_dir,
            override=override,
            fallback=fallback,
        )
    except ValueError as exc:
        shutil.rmtree(source_dir.parent, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workspace = album_workspace(settings.data_root, workspace_name)
    staging = source_dir.parent
    staging.rename(workspace)
    return workspace, workspace_name, naming_source


def _enrich_job(job) -> dict:
    payload = job.to_dict()
    payload["outputs"] = list_job_outputs(job)
    payload["log_download_url"] = f"/api/jobs/{job.id}/log/download"
    payload["scheduled_deletions"] = [
        entry
        for entry in retention_scheduler.list_pending()
        if entry.get("job_id") == job.id
    ]
    return payload


def _safe_extract_zip(archive: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in archive.infolist():
        if member.is_dir():
            continue
        # A symlink in a zip can point outside dest even when its name is safe.
        mode = member.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise HTTPException(status_code=400, detail="Zip files cannot contain symlinks")
        try:
            safe_resolve_under(dest, member.filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Zip contains unsafe paths") from exc
    archive.extractall(dest)


def create_app() -> FastAPI:
    settings = Settings.from_env()
    settings.data_root.mkdir(parents=True, exist_ok=True)
    ensure_schema(settings)
    job_manager.configure_storage(settings.data_root)
    retention_scheduler.configure(
        settings.data_root,
        delay_hours=settings.retention_delay_hours,
    )

    app = FastAPI(title="Album DVD Burner", version=__version__)

    @app.on_event("shutdown")
    def shutdown_scheduler() -> None:
        retention_scheduler.stop()

    @app.get("/api/health")
    def health() -> dict:
        drive = Path(settings.dvd_device)
        drive_exists = drive.is_block_device() and os.access(drive, os.R_OK | os.W_OK)
        return {
            "status": "ok",
            "dvd_device": settings.dvd_device,
            "drive_ready": drive_exists,
            "data_root": str(settings.data_root),
            "retention_delay_hours": settings.retention_delay_hours,
            "dvd_standard": settings.dvd_standard,
            "api_key_required": bool(settings.web_api_key),
        }

    @app.get("/api/albums", dependencies=[Depends(verify_api_key)])
    def get_albums(settings: Settings = Depends(get_settings)) -> list[dict]:
        workspaces = list_album_workspaces(settings.data_root)
        order = {name: index for index, name in enumerate(_load_album_order(settings))}
        workspaces.sort(key=lambda path: (order.get(path.name, len(order)), path.name))
        return [_scan_album(path) for path in workspaces]

    @app.put("/api/albums/order", dependencies=[Depends(verify_api_key)])
    def set_album_order(
        body: OrderRequest,
        settings: Settings = Depends(get_settings),
    ) -> dict:
        existing = {path.name for path in list_album_workspaces(settings.data_root)}
        names: list[str] = []
        seen: set[str] = set()
        for name in body.names:
            if name in existing and name not in seen:
                names.append(name)
                seen.add(name)
        for name in sorted(existing - seen):
            names.append(name)
        _save_album_order(settings, names)
        return {"order": names}

    @app.get("/api/albums/{album_name}/artwork", dependencies=[Depends(verify_api_key)])
    def get_album_artwork(
        album_name: str,
        settings: Settings = Depends(get_settings),
    ) -> FileResponse:
        workspace = _resolve_workspace(settings, album_name)
        artwork = find_artwork(workspace)
        if artwork is None or not artwork.is_file():
            raise HTTPException(status_code=404, detail="Album artwork not found")
        return FileResponse(artwork)

    @app.get("/api/burns", dependencies=[Depends(verify_api_key)])
    def get_burns(settings: Settings = Depends(get_settings)) -> list[dict]:
        return list_burns(settings)

    @app.get("/api/next-burn-code", dependencies=[Depends(verify_api_key)])
    def get_next_burn_code(settings: Settings = Depends(get_settings)) -> dict:
        return {"burn_code": next_burn_code(settings)}

    @app.get("/api/jobs", dependencies=[Depends(verify_api_key)])
    def get_jobs() -> list[dict]:
        return [job.to_dict() for job in job_manager.list_jobs()]

    @app.get("/api/retention/pending", dependencies=[Depends(verify_api_key)])
    def get_pending_deletions() -> list[dict]:
        return retention_scheduler.list_pending()

    @app.get("/api/jobs/active", dependencies=[Depends(verify_api_key)])
    def get_active_job() -> dict:
        job = job_manager.active_job()
        if job is None:
            return {"job": None}
        return {"job": _enrich_job(job)}

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
    def get_job(job_id: str) -> dict:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _enrich_job(job)

    @app.get("/api/jobs/{job_id}/log/download", dependencies=[Depends(verify_api_key)])
    def download_job_log(job_id: str):
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.logs and not job.error:
            raise HTTPException(status_code=404, detail="Job log is empty")
        return job_log_response(job)

    @app.get("/api/jobs/{job_id}/download/{artifact_id}", dependencies=[Depends(verify_api_key)])
    def download_job_artifact(
        job_id: str,
        artifact_id: str,
        background_tasks: BackgroundTasks,
    ):
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        try:
            return job_artifact_response(job, artifact_id, background_tasks)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs", dependencies=[Depends(verify_api_key)])
    def create_job(
        body: CreateJobRequest,
        settings: Settings = Depends(get_settings),
    ) -> dict:
        folders = [_resolve_workspace(settings, name) for name in body.albums]
        retention = RetentionOptions.from_dict(body.retention.model_dump())

        if body.standard and body.standard.lower() not in ("ntsc", "pal"):
            raise HTTPException(status_code=400, detail="standard must be ntsc or pal")

        job_settings = settings
        if body.standard:
            job_settings = Settings(
                postgres_host=settings.postgres_host,
                postgres_port=settings.postgres_port,
                postgres_db=settings.postgres_db,
                postgres_user=settings.postgres_user,
                postgres_password=settings.postgres_password,
                dvd_device=settings.dvd_device,
                dvd_standard=body.standard.lower(),
                data_root=settings.data_root,
                burn_id_prefix=settings.burn_id_prefix,
                web_api_key=settings.web_api_key,
                retention_delay_hours=settings.retention_delay_hours,
            )

        if job_manager.running_job() is not None:
            raise HTTPException(status_code=409, detail="A job is already running")

        try:
            job = job_manager.create(
                folders,
                job_settings,
                burn=body.burn,
                eject_after_burn=body.eject_after_burn,
                retention=retention,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _enrich_job(job)

    @app.post("/api/upload/zip", dependencies=[Depends(verify_api_key)])
    async def upload_zip(
        file: UploadFile = File(...),
        album_name: str | None = Form(default=None),
        settings: Settings = Depends(get_settings),
    ) -> dict:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Upload a .zip file")

        dest = _staging_source_dir(settings)
        try:
            content = await file.read()
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                _safe_extract_zip(archive, dest)
            _require_staging_audio(dest)

            override = album_name.strip() if album_name and album_name.strip() else None
            fallback = Path(file.filename).stem
            workspace, _, naming_source = _finalize_upload(
                settings,
                dest,
                override=override,
                fallback=fallback,
            )
        except HTTPException:
            raise
        except Exception as exc:
            _cleanup_staging(dest)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        result = _scan_album(workspace)
        result["naming_source"] = naming_source
        return result

    @app.post("/api/upload/folder", dependencies=[Depends(verify_api_key)])
    async def upload_folder(
        files: list[UploadFile] = File(...),
        album_name: str | None = Form(default=None),
        album_fallback: str | None = Form(default=None),
        settings: Settings = Depends(get_settings),
    ) -> dict:
        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded")

        dest = _staging_source_dir(settings)

        try:
            folder_fallback = None
            for upload in files:
                if not upload.filename:
                    continue
                if not folder_fallback and "/" in upload.filename:
                    folder_fallback = upload.filename.split("/")[0]
                try:
                    target = safe_resolve_under(dest, upload.filename)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="Invalid upload path") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    shutil.copyfileobj(upload.file, handle)

            _require_staging_audio(dest)

            override = album_name.strip() if album_name and album_name.strip() else None
            fallback = (
                album_fallback.strip()
                if album_fallback and album_fallback.strip()
                else None
            ) or folder_fallback
            workspace, _, naming_source = _finalize_upload(
                settings,
                dest,
                override=override,
                fallback=fallback,
            )
        except HTTPException:
            raise
        except Exception as exc:
            _cleanup_staging(dest)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        result = _scan_album(workspace)
        result["naming_source"] = naming_source
        return result

    @app.patch("/api/albums/{album_name}", dependencies=[Depends(verify_api_key)])
    def rename_album(
        album_name: str,
        body: RenameAlbumRequest,
        settings: Settings = Depends(get_settings),
    ) -> dict:
        running = job_manager.running_job()
        if running and album_name in running.album_names:
            raise HTTPException(
                status_code=409,
                detail="Cannot rename album while it is part of a running job",
            )
        workspace = _resolve_workspace(settings, album_name)

        try:
            new_name = sanitize_name(body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        target = album_workspace(settings.data_root, new_name)
        if target.resolve() == workspace.resolve():
            return _scan_album(workspace)
        if target.exists():
            raise HTTPException(
                status_code=409,
                detail=f"An album named {new_name!r} already exists",
            )

        workspace.rename(target)
        return _scan_album(target)

    @app.delete("/api/albums", dependencies=[Depends(verify_api_key)])
    def delete_all_albums(settings: Settings = Depends(get_settings)) -> dict:
        running = job_manager.running_job()
        running_names = set(running.album_names) if running else set()

        deleted: list[str] = []
        skipped: list[str] = []
        for workspace in list_album_workspaces(settings.data_root):
            if workspace.name in running_names:
                skipped.append(workspace.name)
                continue
            shutil.rmtree(workspace)
            deleted.append(workspace.name)

        return {"deleted": deleted, "skipped": skipped}

    @app.delete("/api/albums/{album_name}", dependencies=[Depends(verify_api_key)])
    def delete_album(album_name: str, settings: Settings = Depends(get_settings)) -> dict:
        running = job_manager.running_job()
        if running and album_name in running.album_names:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete album while it is part of a running job",
            )
        workspace = _resolve_workspace(settings, album_name)
        shutil.rmtree(workspace)
        return {"deleted": album_name}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
