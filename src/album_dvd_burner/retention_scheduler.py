from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .workspaces import JOBS_DIR


@dataclass
class ScheduledDeletion:
    id: str
    path: str
    delete_at: str
    label: str
    burn_code: str | None = None
    job_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "delete_at": self.delete_at,
            "label": self.label,
            "burn_code": self.burn_code,
            "job_id": self.job_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledDeletion":
        return cls(
            id=data["id"],
            path=data["path"],
            delete_at=data["delete_at"],
            label=data["label"],
            burn_code=data.get("burn_code"),
            job_id=data.get("job_id"),
        )


class RetentionScheduler:
    def __init__(self) -> None:
        self._entries: dict[str, ScheduledDeletion] = {}
        self._lock = threading.Lock()
        self._storage_dir: Path | None = None
        self._data_root: Path | None = None
        self._delay_hours: float = 3.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def configure(self, data_root: Path, *, delay_hours: float) -> None:
        self._data_root = data_root.resolve()
        self._delay_hours = max(0.0, delay_hours)
        self._storage_dir = data_root / ".retention-queue"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._load()
        self.start()

    @property
    def delay_hours(self) -> float:
        return self._delay_hours

    def _load(self) -> None:
        if self._storage_dir is None:
            return
        loaded: dict[str, ScheduledDeletion] = {}
        for file in self._storage_dir.glob("*.json"):
            try:
                entry = ScheduledDeletion.from_dict(json.loads(file.read_text(encoding="utf-8")))
                loaded[entry.id] = entry
            except (json.JSONDecodeError, KeyError):
                continue
        with self._lock:
            self._entries = loaded

    def _persist(self, entry: ScheduledDeletion) -> None:
        if self._storage_dir is None:
            return
        path = self._storage_dir / f"{entry.id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entry.to_dict(), indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _remove_entry(self, entry_id: str) -> None:
        with self._lock:
            self._entries.pop(entry_id, None)
        if self._storage_dir is not None:
            (self._storage_dir / f"{entry_id}.json").unlink(missing_ok=True)

    def schedule(
        self,
        target: Path,
        *,
        label: str,
        burn_code: str | None = None,
        job_id: str | None = None,
        delay_hours: float | None = None,
    ) -> str | None:
        if not target.exists():
            return None

        delay = self._delay_hours if delay_hours is None else max(0.0, delay_hours)
        if delay <= 0:
            return None

        resolved = target.resolve()
        if self._data_root and not resolved.is_relative_to(self._data_root):
            return None

        delete_at = datetime.now(timezone.utc) + timedelta(hours=delay)
        delete_at_str = delete_at.isoformat()

        with self._lock:
            for entry in self._entries.values():
                if entry.path == str(resolved):
                    entry.delete_at = delete_at_str
                    entry.label = label
                    self._persist(entry)
                    return (
                        f"Scheduled {label} for deletion at "
                        f"{delete_at.astimezone().strftime('%Y-%m-%d %H:%M')} "
                        f"({delay:g}h grace period)"
                    )

            entry = ScheduledDeletion(
                id=str(uuid.uuid4()),
                path=str(resolved),
                delete_at=delete_at_str,
                label=label,
                burn_code=burn_code,
                job_id=job_id,
            )
            self._entries[entry.id] = entry

        self._persist(entry)
        return (
            f"Scheduled {label} for deletion at "
            f"{delete_at.astimezone().strftime('%Y-%m-%d %H:%M')} "
            f"({delay:g}h grace period)"
        )

    def list_pending(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        pending = []
        with self._lock:
            entries = list(self._entries.values())

        for entry in sorted(entries, key=lambda item: item.delete_at):
            delete_at = datetime.fromisoformat(entry.delete_at)
            pending.append(
                {
                    **entry.to_dict(),
                    "due": delete_at <= now,
                    "seconds_remaining": max(0, int((delete_at - now).total_seconds())),
                }
            )
        return pending

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.process_due()
            self._stop.wait(60)

    def process_due(self) -> list[str]:
        from .retention import _prune_empty_parents, _remove_path

        now = datetime.now(timezone.utc)
        messages: list[str] = []

        with self._lock:
            due = [
                entry
                for entry in self._entries.values()
                if datetime.fromisoformat(entry.delete_at) <= now
            ]

        for entry in due:
            path = Path(entry.path)
            if _remove_path(path):
                messages.append(f"Deleted scheduled file: {path}")
            self._remove_entry(entry.id)

            if self._data_root and path.name == "output":
                job_folder = path.parent
                jobs_root = self._data_root / JOBS_DIR
                if job_folder.parent.resolve() == jobs_root.resolve():
                    _prune_empty_parents(job_folder, jobs_root)
                    _prune_empty_parents(jobs_root, self._data_root)

        return messages


retention_scheduler = RetentionScheduler()
