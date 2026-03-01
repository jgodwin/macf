from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path


@dataclass
class FileLock:
    file_path: str
    agent_id: str
    acquired_at: datetime
    expires_at: datetime


class FileManager:
    DEFAULT_LOCK_TIMEOUT = 180  # 3 minutes — auto-release to prevent deadlock

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, FileLock] = {}

    def _resolve(self, file_path: str) -> Path:
        resolved = (self.workspace_dir / file_path).resolve()
        if not str(resolved).startswith(str(self.workspace_dir.resolve())):
            raise ValueError("Path traversal not allowed")
        return resolved

    def create_file(self, file_path: str, content: str = "") -> None:
        full = self._resolve(file_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    def read_file(self, file_path: str) -> str:
        full = self._resolve(file_path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return full.read_text()

    def list_files(self) -> list[str]:
        return [
            str(p.relative_to(self.workspace_dir))
            for p in self.workspace_dir.rglob("*")
            if p.is_file()
        ]

    def _is_lock_valid(self, lock: FileLock) -> bool:
        return datetime.now(timezone.utc) < lock.expires_at

    def acquire_lock(
        self, file_path: str, agent_id: str, timeout_seconds: int | None = None
    ) -> bool:
        if timeout_seconds is None:
            timeout_seconds = self.DEFAULT_LOCK_TIMEOUT
        full = self._resolve(file_path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        existing = self._locks.get(file_path)
        if existing and self._is_lock_valid(existing):
            if existing.agent_id == agent_id:
                return True  # already holds it
            return False
        now = datetime.now(timezone.utc)
        self._locks[file_path] = FileLock(
            file_path=file_path,
            agent_id=agent_id,
            acquired_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
        )
        return True

    def release_lock(self, file_path: str, agent_id: str) -> None:
        lock = self._locks.get(file_path)
        if not lock or not self._is_lock_valid(lock):
            return  # no lock to release
        if lock.agent_id != agent_id:
            raise ValueError(f"Lock on {file_path} not held by {agent_id}")
        del self._locks[file_path]

    def release_all_locks(self, agent_id: str) -> None:
        to_remove = [
            fp for fp, lock in self._locks.items()
            if lock.agent_id == agent_id
        ]
        for fp in to_remove:
            del self._locks[fp]

    def get_lock_info(self, file_path: str) -> dict | None:
        lock = self._locks.get(file_path)
        if not lock or not self._is_lock_valid(lock):
            return None
        return {
            "file_path": lock.file_path,
            "agent_id": lock.agent_id,
            "acquired_at": lock.acquired_at.isoformat(),
            "expires_at": lock.expires_at.isoformat(),
        }

    def write_file(self, file_path: str, content: str, agent_id: str) -> None:
        full = self._resolve(file_path)
        lock = self._locks.get(file_path)
        if not lock or not self._is_lock_valid(lock):
            raise PermissionError(f"Must acquire lock on {file_path} before writing")
        if lock.agent_id != agent_id:
            raise PermissionError(
                f"Lock on {file_path} held by {lock.agent_id}, not {agent_id}"
            )
        full.write_text(content)
