"""Crash-safe atomic project store with deterministic reopen and undo/redo history.

Persists each WisprStudio project as a checksummed JSON envelope written via
same-directory temp file + `flush()` + `os.fsync()` + `os.replace()`, paired
with a last-known-good `.bak` recovery file so mid-save crashes or truncated
writes recover cleanly on `reopen()` without losing prior project state.

Pure Python stdlib — zero `torch` dependency.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.path_security import UnsafePath, resolve_within

PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_MAX_HISTORY = 50


class ProjectStoreError(RuntimeError):
    """Base error for project store failures."""


class ProjectNotFoundError(ProjectStoreError):
    """Raised when a project ID does not exist on disk."""


class ProjectUndoUnavailableError(ProjectStoreError):
    """Raised when `undo()` or `redo()` is requested on an empty stack."""


class ProjectCorruptError(ProjectStoreError):
    """Raised when both primary and backup project files are unrecoverable."""


def _state_digest(state: dict[str, Any]) -> str:
    canonical = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    # Self-parse check before touching any file on disk.
    json.loads(serialized.decode("utf-8"))

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise


class ProjectStore:
    """Crash-safe atomic project persistence + bounded undo/redo history."""

    def __init__(
        self,
        root_dir: str | os.PathLike[str] | None = None,
        *,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        if root_dir is None:
            from core import config as _cfg

            base = Path(_cfg.DATA_DIR) / "projects"
        else:
            base = Path(root_dir)
        self.root_dir = base
        self.max_history = max(1, int(max_history))
        self._lock = threading.RLock()

    def _validate_id(self, project_id: str) -> str:
        pid = str(project_id or "").strip()
        if not PROJECT_ID_RE.fullmatch(pid):
            raise ValueError(f"Invalid project_id: {project_id!r}")
        return pid

    def _primary_path(self, project_id: str) -> Path:
        pid = self._validate_id(project_id)
        try:
            return resolve_within(self.root_dir, f"{pid}.project.json")
        except UnsafePath as exc:
            raise ValueError(f"Unsafe project_id: {project_id!r}") from exc

    def _backup_path(self, project_id: str) -> Path:
        pid = self._validate_id(project_id)
        try:
            return resolve_within(self.root_dir, f"{pid}.project.json.bak")
        except UnsafePath as exc:
            raise ValueError(f"Unsafe project_id: {project_id!r}") from exc

    def _cleanup_orphan_temps(self, project_id: str) -> None:
        pid = self._validate_id(project_id)
        if not self.root_dir.is_dir():
            return
        prefix = f".{pid}.project.json."
        for entry in os.scandir(self.root_dir):
            if entry.name.startswith(prefix) and entry.name.endswith(".tmp") and entry.is_file(follow_symlinks=False):
                try:
                    os.unlink(entry.path)
                except OSError:
                    pass

    @staticmethod
    def _parse_and_verify(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return None
        state = data.get("state")
        if not isinstance(state, dict):
            return None
        expected_sha = data.get("state_sha256")
        if not isinstance(expected_sha, str) or _state_digest(state) != expected_sha:
            return None
        if not isinstance(data.get("undo_stack"), list) or not isinstance(data.get("redo_stack"), list):
            return None
        return data

    def create(
        self,
        *,
        name: str,
        state: dict[str, Any] | None = None,
        project_id: str | None = None,
        video_path: str | None = None,
        audio_path: str | None = None,
        duration: float | None = None,
    ) -> dict[str, Any]:
        pid = self._validate_id(project_id or uuid.uuid4().hex[:8])
        clean_name = str(name or "").strip() or "Untitled Project"
        clean_state = copy.deepcopy(state) if isinstance(state, dict) else {}
        now = time.time()
        envelope: dict[str, Any] = {
            "schema_version": 1,
            "id": pid,
            "name": clean_name,
            "video_path": video_path,
            "audio_path": audio_path,
            "duration": float(duration) if duration is not None else 0.0,
            "state": clean_state,
            "state_sha256": _state_digest(clean_state),
            "revision": 1,
            "undo_stack": [],
            "redo_stack": [],
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            primary = self._primary_path(pid)
            backup = self._backup_path(pid)
            _atomic_write_json(primary, envelope)
            _atomic_write_json(backup, envelope)
            self._cleanup_orphan_temps(pid)
        return self._public_view(envelope, recovered=False)

    def save(
        self,
        project_id: str,
        *,
        state: dict[str, Any],
        name: str | None = None,
        video_path: str | None = None,
        audio_path: str | None = None,
        duration: float | None = None,
    ) -> dict[str, Any]:
        """Atomically save a new project state, recording an undo frame if `state` changed."""
        pid = self._validate_id(project_id)
        if not isinstance(state, dict):
            raise ValueError("Project state must be a JSON object/dict")
        new_state = copy.deepcopy(state)
        new_digest = _state_digest(new_state)

        with self._lock:
            primary = self._primary_path(pid)
            backup = self._backup_path(pid)
            existing, _ = self._load_envelope_locked(pid, allow_missing=True)
            if existing is None:
                return self.create(
                    project_id=pid,
                    name=name or "Untitled Project",
                    state=new_state,
                    video_path=video_path,
                    audio_path=audio_path,
                    duration=duration,
                )

            # Backup the verified current primary before writing the new revision.
            _atomic_write_json(backup, existing)

            undo_stack = list(existing.get("undo_stack") or [])
            redo_stack = list(existing.get("redo_stack") or [])
            revision = int(existing.get("revision", 1))

            if new_digest != existing["state_sha256"]:
                undo_stack.append(copy.deepcopy(existing["state"]))
                if len(undo_stack) > self.max_history:
                    undo_stack = undo_stack[-self.max_history :]
                redo_stack = []
                revision += 1

            updated: dict[str, Any] = {
                **existing,
                "name": (str(name).strip() if name is not None and str(name).strip() else existing["name"]),
                "video_path": video_path if video_path is not None else existing.get("video_path"),
                "audio_path": audio_path if audio_path is not None else existing.get("audio_path"),
                "duration": float(duration) if duration is not None else existing.get("duration", 0.0),
                "state": new_state,
                "state_sha256": new_digest,
                "revision": revision,
                "undo_stack": undo_stack,
                "redo_stack": redo_stack,
                "updated_at": time.time(),
            }
            _atomic_write_json(primary, updated)
            _atomic_write_json(backup, updated)
            self._cleanup_orphan_temps(pid)
            return self._public_view(updated, recovered=False)

    def _load_envelope_locked(
        self,
        project_id: str,
        *,
        allow_missing: bool = False,
    ) -> tuple[dict[str, Any] | None, bool]:
        primary = self._primary_path(project_id)
        backup = self._backup_path(project_id)
        self._cleanup_orphan_temps(project_id)

        data = self._parse_and_verify(primary)
        if data is not None:
            return data, False

        bak_data = self._parse_and_verify(backup)
        if bak_data is not None:
            # Self-heal primary atomically from the verified last-good `.bak`!
            _atomic_write_json(primary, bak_data)
            return bak_data, True

        if not primary.exists() and not backup.exists():
            if allow_missing:
                return None, False
            raise ProjectNotFoundError(f"Project {project_id!r} not found")
        raise ProjectCorruptError(
            f"Project {project_id!r} is corrupted and no valid backup exists"
        )

    def reopen(self, project_id: str) -> dict[str, Any]:
        """Reopen a persisted project, recovering automatically from `.bak` if interrupted mid-save."""
        pid = self._validate_id(project_id)
        with self._lock:
            envelope, recovered = self._load_envelope_locked(pid)
            assert envelope is not None
            return self._public_view(envelope, recovered=recovered)

    load = reopen

    def undo(self, project_id: str) -> dict[str, Any]:
        """Restore the previous saved state and push current state onto `redo_stack`."""
        pid = self._validate_id(project_id)
        with self._lock:
            envelope, _ = self._load_envelope_locked(pid)
            assert envelope is not None
            undo_stack = list(envelope.get("undo_stack") or [])
            if not undo_stack:
                raise ProjectUndoUnavailableError(f"Nothing to undo for project {pid!r}")
            redo_stack = list(envelope.get("redo_stack") or [])
            redo_stack.append(copy.deepcopy(envelope["state"]))
            if len(redo_stack) > self.max_history:
                redo_stack = redo_stack[-self.max_history :]
            restored_state = undo_stack.pop()
            updated = {
                **envelope,
                "state": restored_state,
                "state_sha256": _state_digest(restored_state),
                "revision": int(envelope.get("revision", 1)) + 1,
                "undo_stack": undo_stack,
                "redo_stack": redo_stack,
                "updated_at": time.time(),
            }
            primary = self._primary_path(pid)
            backup = self._backup_path(pid)
            _atomic_write_json(primary, updated)
            _atomic_write_json(backup, updated)
            return self._public_view(updated, recovered=False)

    def redo(self, project_id: str) -> dict[str, Any]:
        """Re-apply the most recently undone state."""
        pid = self._validate_id(project_id)
        with self._lock:
            envelope, _ = self._load_envelope_locked(pid)
            assert envelope is not None
            redo_stack = list(envelope.get("redo_stack") or [])
            if not redo_stack:
                raise ProjectUndoUnavailableError(f"Nothing to redo for project {pid!r}")
            undo_stack = list(envelope.get("undo_stack") or [])
            undo_stack.append(copy.deepcopy(envelope["state"]))
            if len(undo_stack) > self.max_history:
                undo_stack = undo_stack[-self.max_history :]
            restored_state = redo_stack.pop()
            updated = {
                **envelope,
                "state": restored_state,
                "state_sha256": _state_digest(restored_state),
                "revision": int(envelope.get("revision", 1)) + 1,
                "undo_stack": undo_stack,
                "redo_stack": redo_stack,
                "updated_at": time.time(),
            }
            primary = self._primary_path(pid)
            backup = self._backup_path(pid)
            _atomic_write_json(primary, updated)
            _atomic_write_json(backup, updated)
            return self._public_view(updated, recovered=False)

    def rename(self, project_id: str, new_name: str) -> dict[str, Any]:
        pid = self._validate_id(project_id)
        clean_name = str(new_name or "").strip()
        if not clean_name:
            raise ValueError("Project name cannot be empty")
        with self._lock:
            envelope, _ = self._load_envelope_locked(pid, allow_missing=True)
            if envelope is None:
                raise ProjectNotFoundError(f"Project {pid!r} not found")
            updated = {
                **envelope,
                "name": clean_name,
                "updated_at": time.time(),
            }
            _atomic_write_json(self._primary_path(pid), updated)
            _atomic_write_json(self._backup_path(pid), updated)
            return self._public_view(updated, recovered=False)

    def delete(self, project_id: str) -> None:
        pid = self._validate_id(project_id)
        with self._lock:
            self._cleanup_orphan_temps(pid)
            for p in (self._primary_path(pid), self._backup_path(pid)):
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass

    @staticmethod
    def _public_view(envelope: dict[str, Any], *, recovered: bool) -> dict[str, Any]:
        return {
            "id": envelope["id"],
            "name": envelope["name"],
            "video_path": envelope.get("video_path"),
            "audio_path": envelope.get("audio_path"),
            "duration": envelope.get("duration", 0.0),
            "state": copy.deepcopy(envelope["state"]),
            "state_sha256": envelope["state_sha256"],
            "revision": envelope["revision"],
            "can_undo": bool(envelope.get("undo_stack")),
            "can_redo": bool(envelope.get("redo_stack")),
            "undo_depth": len(envelope.get("undo_stack") or []),
            "redo_depth": len(envelope.get("redo_stack") or []),
            "recovered_from_backup": recovered,
            "created_at": envelope["created_at"],
            "updated_at": envelope["updated_at"],
        }


_default_project_store_dir: Path | None = None


def set_default_project_store_dir(path: str | os.PathLike[str] | None) -> None:
    global _default_project_store_dir
    _default_project_store_dir = Path(path) if path is not None else None


def get_default_project_store() -> ProjectStore:
    return ProjectStore(_default_project_store_dir)
