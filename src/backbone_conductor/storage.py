"""Git-backed, transactional persistence for the Backbone protocol.

The JSON snapshot is authoritative. Markdown and per-object JSON files are
generated views. Commits use a private index so application changes staged by
the repository's owner are never accidentally included in a Backbone commit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from filelock import FileLock, Timeout

from backbone_conductor.models import BackboneState

T = TypeVar("T")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")


class StorageError(RuntimeError):
    """A repository cannot safely complete a Backbone storage operation."""


class GitStore:
    """Persist snapshots and audit records in an existing working-tree repo."""

    def __init__(self, repo: str | Path, *, lock_timeout: float = 10) -> None:
        self.root = Path(repo).expanduser().resolve()
        if not self.root.is_dir():
            raise StorageError(f"Repository directory does not exist: {self.root}")
        self.root = Path(self._git("rev-parse", "--show-toplevel").stdout.strip())
        self.git_dir = Path(self._git("rev-parse", "--absolute-git-dir").stdout.strip())
        self.path = self.root / ".backbone"
        self._index = Path(
            self._git("rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip()
        )
        self._lock = FileLock(self.git_dir / "backbone.lock", timeout=lock_timeout)

    def _git(
        self,
        *args: str,
        check: bool = True,
        env: dict[str, str] | None = None,
        input: str | None = None,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        git_env = os.environ.copy()
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            git_env.pop(key, None)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        git_env.update(env or {})
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.root,
                env=git_env,
                input=input,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StorageError(f"Could not run Git: {exc}") from exc
        if check and result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise StorageError(f"git {args[0]} failed: {detail}")
        return result

    def _head(self) -> str | None:
        result = self._git("rev-parse", "--verify", "HEAD", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def _ensure_safe(self) -> None:
        if self.path.is_symlink():
            raise StorageError(".backbone must not be a symbolic link")
        if self.path.exists() and not self.path.is_dir():
            raise StorageError(".backbone must be a directory")
        if self.path.exists():
            for directory, dirs, files in os.walk(self.path, followlinks=False):
                for name in dirs + files:
                    item = Path(directory) / name
                    if item.is_symlink():
                        raise StorageError(f"Symbolic links are not allowed in .backbone: {item}")
                    if not item.is_file() and not item.is_dir():
                        raise StorageError(f"Unsupported file in .backbone: {item}")

    def _ensure_clean(self) -> None:
        self._ensure_safe()
        status = self._git(
            "status", "--porcelain=v1", "--untracked-files=all", "--ignored", "--", ".backbone"
        ).stdout
        if status:
            raise StorageError(
                ".backbone has uncommitted changes; commit or restore them before continuing"
            )

    def _read(self) -> BackboneState:
        self._ensure_clean()
        state_path = self.path / "state.json"
        if not state_path.is_file():
            raise StorageError("Backbone is not initialized; run backbone init first")
        try:
            state = BackboneState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            raise StorageError(f"Invalid Backbone state: {exc}") from exc
        state.version = (
            self._git("log", "-1", "--format=%H", "--", ".backbone").stdout.strip() or None
        )
        return state

    def read(self) -> BackboneState:
        try:
            with self._lock:
                return self._read()
        except Timeout as exc:
            raise StorageError("Timed out waiting for the Backbone repository lock") from exc

    def init(self) -> BackboneState:
        """Create and commit the initial state, or return the existing state."""
        try:
            with self._lock:
                self._ensure_clean()
                if (self.path / "state.json").exists():
                    return self._read()
                self._commit(BackboneState(), "backbone: initialize")
                return self._read()
        except Timeout as exc:
            raise StorageError("Timed out waiting for the Backbone repository lock") from exc

    def mutate(self, callback: Callable[[BackboneState], T], message: str) -> T:
        """Run a change under the repository lock, then commit it atomically."""
        if not message.strip() or "\x00" in message:
            raise StorageError("A nonempty commit message without NUL characters is required")
        try:
            with self._lock:
                state = self._read()
                previous_version = state.version
                result = callback(state)
                # Validate after callbacks too: dict assignment can bypass model validators.
                state = BackboneState.model_validate(state.model_dump(mode="json"))
                state.parent_version = previous_version
                state.version = None
                self._commit(state, message, expected_version=previous_version)
                return result
        except Timeout as exc:
            raise StorageError("Timed out waiting for the Backbone repository lock") from exc

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    @staticmethod
    def _markdown(kind: str, identifier: str, item: dict[str, Any]) -> str:
        title = item.get("summary") or item.get("problem") or item.get("title") or identifier
        lines = [f"# {kind}: {title}", "", f"ID: `{identifier}`", ""]
        for key, value in item.items():
            if key == "id" or value is None or value == [] or value == {}:
                continue
            lines.extend([f"## {key.replace('_', ' ').capitalize()}", ""])
            if isinstance(value, list):
                lines.extend(f"- {entry}" for entry in value)
            elif isinstance(value, dict):
                lines.extend(["```json", GitStore._json(value).rstrip(), "```"])
            else:
                lines.append(str(value))
            lines.append("")
        return "\n".join(lines)

    def _render(self, state: BackboneState) -> dict[str, str]:
        data = state.model_dump(mode="json")
        # A commit cannot contain its own hash. Resolve it from Git when reading.
        data["version"] = None
        views = {"state.json": self._json(data)}
        overview = [
            "# Backbone",
            "",
            "Generated from `state.json`. Change state through Backbone tools.",
            "",
        ]
        for collection in ("intents", "decisions", "conflicts", "tasks", "sessions"):
            objects = data[collection]
            overview.extend([f"## {collection.capitalize()} ({len(objects)})", ""])
            for identifier, item in sorted(objects.items()):
                if collection == "sessions":
                    # Member/session names are free text, unlike protocol object IDs.
                    filename = "session-" + hashlib.sha256(identifier.encode()).hexdigest()
                elif not _SAFE_ID.fullmatch(identifier) or identifier in {".", ".."}:
                    raise StorageError(f"Unsafe {collection} identifier: {identifier!r}")
                else:
                    filename = identifier
                extension = "md" if collection in {"intents", "decisions", "sessions"} else "json"
                relative = f"{collection}/{filename}.{extension}"
                views[relative] = (
                    self._markdown(collection[:-1].capitalize(), identifier, item)
                    if extension == "md"
                    else self._json(item)
                )
                status = item.get("status", "")
                summary = item.get("summary") or item.get("problem") or item.get("title") or ""
                summary = str(summary).replace("\n", " ")
                overview.append(f"- [{identifier}]({relative}) {status} — {summary}".rstrip())
            if not objects:
                overview.append("None.")
            overview.append("")
        views["BACKBONE.md"] = "\n".join(overview)
        return views

    def _write_views(self, views: dict[str, str]) -> None:
        self._ensure_safe()
        self.path.mkdir(exist_ok=True)
        for collection in ("intents", "decisions", "conflicts", "tasks", "sessions"):
            directory = self.path / collection
            directory.mkdir(exist_ok=True)
            for item in directory.iterdir():
                if item.is_file() and item.suffix in {".json", ".md"}:
                    if item.relative_to(self.path).as_posix() not in views:
                        item.unlink()
        for relative, content in views.items():
            target = self.path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _commit(
        self, state: BackboneState, message: str, *, expected_version: str | None = None
    ) -> None:
        views = self._render(state)
        self._ensure_clean()
        head = self._head()
        if expected_version is not None:
            actual_version = (
                self._git("log", "-1", "--format=%H", head, "--", ".backbone").stdout.strip()
                if head
                else None
            )
            if actual_version != expected_version:
                raise StorageError(
                    "Backbone changed during the transaction; retry from current state"
                )
        branch_result = self._git("symbolic-ref", "-q", "HEAD", check=False)
        ref = branch_result.stdout.strip() if branch_result.returncode == 0 else "HEAD"
        index_lock = Path(f"{self._index}.lock")
        try:
            lock_fd = os.open(index_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise StorageError(
                "Git index is locked by another operation; retry when it finishes"
            ) from exc
        os.close(lock_fd)
        changed_head = False
        commit: str | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="backbone-", dir=self.git_dir) as temp:
                work = Path(temp)
                backup = work / "backup"
                had_backbone = self.path.exists()
                if had_backbone:
                    shutil.copytree(self.path, backup)
                try:
                    self._write_views(views)
                    commit_env = {"GIT_INDEX_FILE": str(work / "commit-index")}
                    self._git("read-tree", head or "--empty", env=commit_env)
                    self._git("add", "--force", "--all", "--", ".backbone", env=commit_env)
                    tree = self._git("write-tree", env=commit_env).stdout.strip()
                    parents = ["-p", head] if head else []
                    commit = self._git(
                        "commit-tree", tree, *parents, input=message + "\n"
                    ).stdout.strip()

                    # Prepare an index which retains every unrelated staged change.
                    user_index = work / "user-index"
                    if self._index.exists():
                        shutil.copy2(self._index, user_index)
                    user_env = {"GIT_INDEX_FILE": str(user_index)}
                    if not user_index.exists():
                        self._git("read-tree", head or "--empty", env=user_env)
                    self._git("reset", "-q", commit, "--", ".backbone", env=user_env)
                    shutil.copy2(user_index, index_lock)

                    current_branch = self._git("symbolic-ref", "-q", "HEAD", check=False)
                    current_ref = (
                        current_branch.stdout.strip() if current_branch.returncode == 0 else "HEAD"
                    )
                    if current_ref != ref:
                        raise StorageError(
                            "Git branch changed during the Backbone transaction; retry"
                        )
                    # Compare-and-swap prevents overwriting a concurrent Git commit.
                    self._git("update-ref", "-m", message.splitlines()[0], ref, commit, head or "")
                    changed_head = True
                    os.replace(index_lock, self._index)
                except BaseException:
                    if changed_head and commit:
                        # Roll back only if our commit is still the current tip.
                        if head:
                            self._git("update-ref", ref, head, commit)
                        else:
                            self._git("update-ref", "-d", ref, commit)
                    if self.path.exists():
                        shutil.rmtree(self.path)
                    if had_backbone:
                        shutil.copytree(backup, self.path)
                    raise
        finally:
            index_lock.unlink(missing_ok=True)

    def log(self, limit: int = 50) -> list[dict[str, str]]:
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise StorageError("Log limit must be between 1 and 1000")
        with self._lock:
            self._ensure_clean()
            if self._head() is None:
                return []
            output = self._git(
                "log", f"-{limit}", "--format=%H%x00%an%x00%aI%x00%s", "--", ".backbone"
            ).stdout
            return [
                dict(
                    zip(
                        ("commit", "author", "timestamp", "message"),
                        line.split("\x00", 3),
                        strict=True,
                    )
                )
                for line in output.splitlines()
                if line
            ]

    def sync(self, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
        """Explicitly push the current branch; never pull or force-push."""
        with self._lock:
            state = self._read()
            remotes = self._git("remote").stdout.splitlines()
            if remote.startswith("-") or remote not in remotes:
                raise StorageError(f"Unknown Git remote: {remote!r}")
            if branch is None:
                result = self._git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
                if result.returncode:
                    raise StorageError("Detached HEAD requires an explicit destination branch")
                branch = result.stdout.strip()
            if (
                branch.startswith("-")
                or self._git("check-ref-format", f"refs/heads/{branch}", check=False).returncode
            ):
                raise StorageError(f"Invalid destination branch: {branch!r}")
            result = self._git(
                "push", "--porcelain", "--", remote, f"HEAD:refs/heads/{branch}", timeout=120
            )
            return {
                "ok": True,
                "remote": remote,
                "branch": branch,
                "version": state.version,
                "detail": result.stdout.strip(),
            }

    def _resolve_revision(self, revision: str) -> str:
        if not revision or revision.startswith("-") or "\x00" in revision:
            raise StorageError(f"Invalid Git revision: {revision!r}")
        result = self._git(
            "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}", check=False
        )
        if result.returncode:
            raise StorageError(f"Unknown Git revision: {revision!r}")
        return result.stdout.strip()

    def check_diff(self, base_ref: str, branch: str) -> dict[str, Any]:
        with self._lock:
            base, tip = self._resolve_revision(base_ref), self._resolve_revision(branch)
            comparison = f"{base}...{tip}"
            # Both sides of a rename affect scope/forbidden-path checks. Git's
            # default name-only output reports only the rename destination.
            paths = self._git("diff", "--no-renames", "--name-only", "-z", comparison, "--").stdout
            result = self._git("diff", "--check", comparison, "--", check=False)
            return {
                "ok": result.returncode == 0,
                "detail": (result.stdout + result.stderr).strip(),
                "changed_paths": [path for path in paths.split("\x00") if path],
            }
