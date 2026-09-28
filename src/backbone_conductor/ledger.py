"""Optional metadata-only Git branch in a hidden linked worktree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import GitStore, StorageError

LEDGER_BRANCH = "backbone"


def ledger_path(source: GitStore) -> Path:
    common = source._git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return Path(common).resolve() / "backbone-ledger"


def open_ledger(source: GitStore, branch: str) -> GitStore:
    if branch != LEDGER_BRANCH:
        raise StorageError(f"Only the {LEDGER_BRANCH!r} ledger branch is supported")
    path = ledger_path(source)
    if not path.is_dir():
        raise StorageError(
            "Backbone ledger worktree is missing; run ledger create or ledger attach"
        )
    ledger = GitStore(path)
    current = ledger._git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if current.returncode or current.stdout.strip() != branch:
        raise StorageError("Ledger worktree is not on the backbone branch")
    if ledger.git_dir == source.git_dir:
        raise StorageError("Ledger and source must use distinct Git worktrees")
    return ledger


def create_ledger(repo: str | Path) -> dict[str, Any]:
    """Create a metadata-only orphan branch without altering the source checkout."""
    source = GitStore(repo)
    path = ledger_path(source)
    if path.exists():
        raise StorageError(f"Ledger worktree already exists: {path}")
    if (
        source._git(
            "show-ref", "--verify", "--quiet", f"refs/heads/{LEDGER_BRANCH}", check=False
        ).returncode
        == 0
    ):
        raise StorageError("Backbone branch already exists; use ledger attach")
    remote_branches = source._git(
        "for-each-ref", "--format=%(refname)", "refs/remotes"
    ).stdout.splitlines()
    if any(ref.endswith(f"/{LEDGER_BRANCH}") for ref in remote_branches):
        raise StorageError("A remote Backbone branch is available; use ledger attach")
    if (source.path / "state.json").exists():
        raise StorageError("Existing inline Backbone state needs an explicit migration")
    if source._head() is None:
        raise StorageError("Commit source code before creating a separate Backbone branch")
    source_head = source._head()
    source._git("worktree", "add", "--detach", str(path), source_head)
    try:
        ledger = GitStore(path)
        ledger._git("switch", "--orphan", LEDGER_BRANCH)
        state = ledger.init()
        if source._head() != source_head:
            raise StorageError("Source branch changed during ledger creation")
        return {"branch": LEDGER_BRANCH, "worktree": str(path), "version": state.version}
    except BaseException:
        source._git("worktree", "remove", "--force", str(path), check=False)
        raise


def attach_ledger(repo: str | Path, remote: str = "origin") -> dict[str, Any]:
    """Attach the existing local or remote metadata branch to this clone."""
    source = GitStore(repo)
    path = ledger_path(source)
    if path.exists():
        raise StorageError(f"Ledger worktree already exists: {path}")
    if source._git(
        "show-ref", "--verify", "--quiet", f"refs/heads/{LEDGER_BRANCH}", check=False
    ).returncode:
        remotes = source._git("remote").stdout.splitlines()
        if remote.startswith("-") or remote not in remotes:
            raise StorageError(f"Unknown Git remote: {remote!r}")
        source._git(
            "fetch",
            "--no-tags",
            remote,
            f"refs/heads/{LEDGER_BRANCH}:refs/heads/{LEDGER_BRANCH}",
            timeout=120,
        )
    tracked = source._git("ls-tree", "-r", "--name-only", LEDGER_BRANCH).stdout.splitlines()
    if not tracked or any(not item.startswith(".backbone/") for item in tracked):
        raise StorageError("Backbone branch must contain metadata files only")
    source._git("worktree", "add", str(path), LEDGER_BRANCH)
    try:
        ledger = open_ledger(source, LEDGER_BRANCH)
        state = ledger.read()
        return {"branch": LEDGER_BRANCH, "worktree": str(path), "version": state.version}
    except BaseException:
        source._git("worktree", "remove", "--force", str(path), check=False)
        raise
