"""Private, redacted operational records for failed advisory review attempts."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path


class ReviewAttemptLog:
    """Append failures outside every Backbone/Git worktree in a private JSONL file."""

    def __init__(self, filename: str | Path, forbidden_roots: tuple[Path, ...]) -> None:
        source = Path(filename).expanduser()
        if not source.is_absolute():
            raise ValueError("Review attempt log path must be absolute")
        self.path = source.absolute()
        parent = self.path.parent.resolve(strict=True)
        if any(parent.is_relative_to(root.resolve()) for root in forbidden_roots):
            raise ValueError("Review attempt log must be outside the repository and Git directory")
        parent_mode = parent.stat().st_mode
        if not stat.S_ISDIR(parent_mode) or parent_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("Review attempt log directory must be private (0700)")
        if parent.stat().st_uid != os.getuid():
            raise ValueError("Review attempt log directory must belong to the current user")
        self._open().close()

    def _open(self):
        if self.path.is_symlink():
            raise ValueError("Review attempt log must be a regular file, not a symlink")
        descriptor = os.open(
            self.path,
            os.O_WRONLY
            | os.O_APPEND
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            os.close(descriptor)
            raise ValueError("Review attempt log must be an owner-only regular file (0600)")
        return os.fdopen(descriptor, "ab", buffering=0)

    def record(
        self,
        *,
        task_id: str,
        model: str,
        provider: str,
        observed_version: str,
        artifact_sha: str,
        phase: str,
        elapsed_ms: float,
        error_type: str,
    ) -> None:
        event = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "model": model,
            "provider": provider,
            "observed_version": observed_version,
            "artifact_sha": artifact_sha,
            "status": "failed",
            "phase": phase,
            "elapsed_ms": elapsed_ms,
            "error_type": error_type,
        }
        data = (json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        with self._open() as stream:
            if stream.write(data) != len(data):
                raise OSError("Incomplete review attempt log write")
            os.fsync(stream.fileno())
