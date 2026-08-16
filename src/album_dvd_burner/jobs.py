from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .config import Settings
from .pipeline import run_pipeline
from .progress import ProgressState
from .workspaces import RetentionOptions


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class JobLog:
    timestamp: str
    stage: str
    message: str


@dataclass
class Job:
    id: str
    album_names: list[str]
    burn: bool
    eject_after_burn: bool = False
    retention: RetentionOptions = field(default_factory=RetentionOptions)
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    burn_code: str | None = None
    iso_path: str | None = None
    output_dir: str | None = None
    error: str | None = None
    progress: ProgressState | None = None
    logs: list[JobLog] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "album_names": self.album_names,
            "burn": self.burn,
            "eject_after_burn": self.eject_after_burn,
            "retention": self.retention.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "burn_code": self.burn_code,
            "iso_path": self.iso_path,
            "output_dir": self.output_dir,
            "error": self.error,
            "progress": self.progress.to_dict() if self.progress else None,
            "logs": [log.__dict__ for log in self.logs],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        logs = [JobLog(**entry) for entry in data.get("logs", [])]
        progress_data = data.get("progress")
        progress = (
            ProgressState(
                stage=progress_data["stage"],
                label=progress_data["label"],
                current=progress_data.get("current", 0),
                total=progress_data.get("total", 0),
            )
            if progress_data
            else None
        )
        status = JobStatus(data["status"])
        if status == JobStatus.RUNNING:
            status = JobStatus.INTERRUPTED

        return cls(
            id=data["id"],
            album_names=data["album_names"],
            burn=data["burn"],
            eject_after_burn=data.get("eject_after_burn", False),
            retention=RetentionOptions.from_dict(data.get("retention")),
            status=status,
            created_at=data["created_at"],
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            burn_code=data.get("burn_code"),
            iso_path=data.get("iso_path"),
            output_dir=data.get("output_dir"),
            error=data.get("error"),
            progress=progress,
            logs=logs,
        )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._storage_dir: Path | None = None

    def configure_storage(self, data_root: Path) -> None:
        self._storage_dir = data_root / ".jobs"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self.load_from_disk()

    def load_from_disk(self) -> None:
        if self._storage_dir is None or not self._storage_dir.exists():
            return

        loaded: dict[str, Job] = {}
        for path in sorted(self._storage_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job = Job.from_dict(data)
                if job.status == JobStatus.INTERRUPTED and not job.error:
                    job.error = "Interrupted by server restart"
                    job.finished_at = job.finished_at or datetime.now(timezone.utc).isoformat()
                loaded[job.id] = job
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        with self._lock:
            self._jobs = loaded
        self._prune_old_jobs()

    def _prune_old_jobs(self, keep: int = 100) -> None:
        if self._storage_dir is None:
            return

        terminal = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.INTERRUPTED}
        finished = [
            job for job in self.list_jobs() if job.status in terminal
        ]
        for job in finished[keep:]:
            with self._lock:
                self._jobs.pop(job.id, None)
            (self._storage_dir / f"{job.id}.json").unlink(missing_ok=True)

    def _persist(self, job: Job) -> None:
        if self._storage_dir is None:
            return
        path = self._storage_dir / f"{job.id}.json"
        path.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def running_job(self) -> Job | None:
        for job in self.list_jobs():
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return job
        return None

    def active_job(self) -> Job | None:
        return self.running_job()

    def create(
        self,
        album_folders: list[Path],
        settings: Settings,
        *,
        burn: bool,
        eject_after_burn: bool = False,
        retention: RetentionOptions | None = None,
    ) -> Job:
        with self._lock:
            if any(
                existing.status in {JobStatus.QUEUED, JobStatus.RUNNING}
                for existing in self._jobs.values()
            ):
                raise RuntimeError("A job is already running")

            job = Job(
                id=str(uuid.uuid4()),
                album_names=[path.name for path in album_folders],
                burn=burn,
                eject_after_burn=eject_after_burn,
                retention=retention or RetentionOptions(),
            )
            self._jobs[job.id] = job

        self._persist(job)

        thread = threading.Thread(
            target=self._run,
            args=(job.id, album_folders, settings, burn, eject_after_burn, job.retention),
            daemon=True,
        )
        thread.start()
        return job

    def _on_progress(
        self,
        job_id: str,
        stage: str,
        message: str,
        progress: ProgressState | None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.logs.append(
                JobLog(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    stage=stage,
                    message=message,
                )
            )
            if progress is not None:
                job.progress = ProgressState(
                    stage=progress.stage,
                    label=progress.label,
                    current=progress.current,
                    total=progress.total,
                )
            snapshot = job
        self._persist(snapshot)

    def _run(
        self,
        job_id: str,
        album_folders: list[Path],
        settings: Settings,
        burn: bool,
        eject_after_burn: bool,
        retention: RetentionOptions,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc).isoformat()
            job.progress = ProgressState(stage="preparing", label="Starting job...", total=1)
            snapshot = job
        self._persist(snapshot)

        try:
            result = run_pipeline(
                album_folders,
                settings,
                burn=burn,
                job_id=job_id,
                retention=retention,
                eject_after_burn=eject_after_burn,
                on_progress=lambda stage, message, progress: self._on_progress(
                    job_id, stage, message, progress
                ),
            )
            with self._lock:
                job = self._jobs[job_id]
                job.status = JobStatus.COMPLETED
                job.burn_code = result.burn_code
                job.iso_path = str(result.iso_path)
                job.output_dir = str(result.output_dir)
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.progress = ProgressState(
                    stage="done",
                    label="Complete",
                    current=1,
                    total=1,
                )
                snapshot = job
            self._persist(snapshot)
        except Exception as exc:  # noqa: BLE001 - surface full error in job UI
            with self._lock:
                job = self._jobs[job_id]
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.finished_at = datetime.now(timezone.utc).isoformat()
                job.progress = ProgressState(stage="error", label="Failed", current=0, total=1)
                job.logs.append(
                    JobLog(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        stage="error",
                        message=str(exc),
                    )
                )
                snapshot = job
            self._persist(snapshot)


job_manager = JobManager()
