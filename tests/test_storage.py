from __future__ import annotations

import json
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from backbone_conductor.models import Decision, Intent, Task
from backbone_conductor.storage import GitStore, StorageError


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Storage Test")
    git(root, "config", "user.email", "storage@example.test")
    return root


def snapshot(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


def increment_counter(repo: str) -> None:
    store = GitStore(repo)

    def change(state):
        current = state.sessions.get("counter", {}).get("value", 0)
        state.sessions["counter"] = {"value": current + 1}

    store.mutate(change, "backbone: increment counter")


def test_init_on_unborn_branch_and_idempotence(repo: Path):
    store = GitStore(repo)
    state = store.init()
    assert state.version == git(repo, "rev-parse", "HEAD")
    assert state.parent_version is None
    assert json.loads((repo / ".backbone/state.json").read_text())["version"] is None
    assert (repo / ".backbone/BACKBONE.md").is_file()
    assert store.init().version == state.version
    assert len(store.log()) == 1
    assert git(repo, "status", "--porcelain") == ""


def test_read_requires_init_and_repo_must_exist(tmp_path: Path, repo: Path):
    with pytest.raises(StorageError, match="not initialized"):
        GitStore(repo).read()
    with pytest.raises(StorageError, match="does not exist"):
        GitStore(tmp_path / "absent")
    with pytest.raises(StorageError, match="not a git repository"):
        GitStore(tmp_path)


def test_persistence_versions_and_generated_views(repo: Path):
    store = GitStore(repo)
    first = store.init()
    intent = Intent(author="alice", problem="重复逻辑", proposed_outcome="One implementation")
    decision = Decision(
        author="alice",
        decision_type="architecture",
        summary="Share the parser",
        rationale="Consistency",
    )
    task = Task(member_id="alice", intent_id=intent.id)

    def change(state):
        state.intents[intent.id] = intent
        state.decisions[decision.id] = decision
        state.tasks[task.id] = task
        state.sessions["alice@example.test"] = {"active": True}
        return intent.id

    assert store.mutate(change, "backbone: add coordination objects") == intent.id
    loaded = GitStore(repo).read()
    assert loaded.intents[intent.id] == intent
    assert loaded.tasks[task.id] == task
    assert loaded.parent_version == first.version
    assert loaded.version != first.version
    assert "重复逻辑" in (repo / f".backbone/intents/{intent.id}.md").read_text()
    assert "Share the parser" in (repo / f".backbone/decisions/{decision.id}.md").read_text()
    assert (
        json.loads((repo / f".backbone/tasks/{task.id}.json").read_text())["member_id"] == "alice"
    )
    assert len(list((repo / ".backbone/sessions").glob("*.md"))) == 1
    entry = store.log(limit=1)[0]
    assert entry["commit"] == loaded.version
    assert entry["author"] == "Storage Test"
    assert entry["message"] == "backbone: add coordination objects"
    assert entry["timestamp"]


def test_unrelated_staged_and_unstaged_changes_preserved(repo: Path):
    file = repo / "application.txt"
    file.write_text("original\n")
    git(repo, "add", "application.txt")
    git(repo, "commit", "-m", "application baseline")
    file.write_text("staged application work\n")
    git(repo, "add", "application.txt")
    file.write_text("unstaged application work\n")
    before = git(repo, "diff", "--cached")
    store = GitStore(repo)
    store.init()
    increment_counter(str(repo))
    assert git(repo, "show", "HEAD:application.txt") == "original"
    assert git(repo, "diff", "--cached") == before
    assert file.read_text() == "unstaged application work\n"
    assert git(repo, "diff", "--name-only", "HEAD~2", "HEAD").splitlines() == [
        ".backbone/BACKBONE.md",
        ".backbone/sessions/" + next((repo / ".backbone/sessions").iterdir()).name,
        ".backbone/state.json",
    ]


def test_initial_commit_does_not_include_existing_staged_files(repo: Path):
    (repo / "uncommitted.txt").write_text("keep staged")
    git(repo, "add", "uncommitted.txt")
    GitStore(repo).init()
    assert "uncommitted.txt" not in git(repo, "ls-tree", "--name-only", "HEAD").splitlines()
    assert git(repo, "diff", "--cached", "--name-only") == "uncommitted.txt"


@pytest.mark.parametrize("failure_command", ["commit-tree", "update-ref"])
def test_commit_failure_rolls_back_files_head_and_index(
    repo: Path, monkeypatch, failure_command: str
):
    store = GitStore(repo)
    original_version = store.init().version
    original_files = snapshot(repo / ".backbone")
    (repo / "staged.txt").write_text("owner work")
    git(repo, "add", "staged.txt")
    original_index = (repo / ".git/index").read_bytes()
    original_git = store._git

    def fail(*args, **kwargs):
        if args[0] == failure_command:
            raise StorageError("simulated Git failure")
        return original_git(*args, **kwargs)

    monkeypatch.setattr(store, "_git", fail)
    with pytest.raises(StorageError, match="simulated"):
        store.mutate(lambda state: state.sessions.update({"new": {"value": 1}}), "backbone: fail")
    assert snapshot(repo / ".backbone") == original_files
    assert (repo / ".git/index").read_bytes() == original_index
    assert git(repo, "rev-parse", "HEAD") == original_version
    assert not (repo / ".git/index.lock").exists()


def test_callback_exception_writes_nothing(repo: Path):
    store = GitStore(repo)
    version = store.init().version

    def fail(state):
        state.sessions["partial"] = {"value": 2}
        raise ValueError("callback failed")

    with pytest.raises(ValueError, match="callback failed"):
        store.mutate(fail, "backbone: fail")
    assert store.read().version == version
    assert not store.read().sessions


def test_external_metadata_commit_cannot_be_overwritten_by_stale_callback(repo: Path):
    store = GitStore(repo)
    store.init()

    def change(state):
        state.sessions["ours"] = {"value": 1}
        # External Git users do not acquire the application's file lock.
        path = repo / ".backbone/state.json"
        external = json.loads(path.read_text())
        external["sessions"]["external"] = {"value": 2}
        path.write_text(json.dumps(external))
        git(repo, "add", ".backbone/state.json")
        git(repo, "commit", "-m", "External metadata update")

    with pytest.raises(StorageError, match="changed during"):
        store.mutate(change, "backbone: stale mutation")
    assert store.read().sessions == {"external": {"value": 2}}
    assert git(repo, "log", "-1", "--format=%s") == "External metadata update"


def test_external_application_commit_can_coexist_with_metadata_mutation(repo: Path):
    store = GitStore(repo)
    store.init()

    def change(state):
        state.sessions["ours"] = {"value": 1}
        (repo / "source.txt").write_text("External source change\n")
        git(repo, "add", "source.txt")
        git(repo, "commit", "-m", "External application update")

    store.mutate(change, "backbone: compatible mutation")
    assert store.read().sessions == {"ours": {"value": 1}}
    assert git(repo, "show", "HEAD:source.txt") == "External source change"
    assert git(repo, "log", "-1", "--format=%s", "HEAD~") == "External application update"


def test_cross_process_lock_prevents_lost_updates(repo: Path):
    store = GitStore(repo)
    store.init()
    with ProcessPoolExecutor(max_workers=3) as pool:
        list(pool.map(increment_counter, [str(repo)] * 6))
    assert store.read().sessions["counter"]["value"] == 6
    assert len(store.log()) == 7
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("dirty_kind", ["modified", "staged", "untracked", "ignored", "deleted"])
def test_dirty_backbone_is_rejected(repo: Path, dirty_kind: str):
    store = GitStore(repo)
    store.init()
    target = repo / ".backbone/state.json"
    if dirty_kind in {"modified", "staged"}:
        target.write_text(target.read_text() + "\n")
        if dirty_kind == "staged":
            git(repo, "add", ".backbone")
    elif dirty_kind == "deleted":
        target.unlink()
    else:
        if dirty_kind == "ignored":
            (repo / ".gitignore").write_text(".backbone/unknown.txt\n")
        (repo / ".backbone/unknown.txt").write_text("uncommitted")
    with pytest.raises(StorageError, match="uncommitted changes"):
        store.mutate(lambda state: None, "backbone: no-op")
    with pytest.raises(StorageError, match="uncommitted changes"):
        store.read()


@pytest.mark.parametrize("nested", [False, True])
def test_symlink_escape_is_rejected(repo: Path, tmp_path: Path, nested: bool):
    outside = tmp_path / "outside"
    outside.mkdir()
    store = GitStore(repo)
    if nested:
        store.init()
        (repo / ".backbone/escape").symlink_to(outside, target_is_directory=True)
    else:
        (repo / ".backbone").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError, match="[Ss]ymbolic link"):
        store.init()
    assert list(outside.iterdir()) == []


def test_arbitrary_session_keys_cannot_escape_repository(repo: Path, tmp_path: Path):
    store = GitStore(repo)
    store.init()
    store.mutate(
        lambda state: state.sessions.update({"../../escaped": {"x": 1}}), "backbone: session"
    )
    assert store.read().sessions["../../escaped"] == {"x": 1}
    assert not (tmp_path / "escaped.md").exists()
    assert len(list((repo / ".backbone/sessions").glob("session-*.md"))) == 1


def test_index_lock_is_respected(repo: Path):
    store = GitStore(repo)
    first = store.init()
    lock = repo / ".git/index.lock"
    lock.write_text("another Git command")
    with pytest.raises(StorageError, match="index is locked"):
        store.mutate(lambda state: state.sessions.update({"x": {}}), "backbone: locked")
    assert lock.read_text() == "another Git command"
    assert store.read().version == first.version


def test_versions_follow_backbone_not_application_commits(repo: Path):
    store = GitStore(repo)
    version = store.init().version
    (repo / "application.py").write_text("print('hello')\n")
    git(repo, "add", "application.py")
    git(repo, "commit", "-m", "application work")
    assert git(repo, "rev-parse", "HEAD") != version
    assert store.read().version == version
    assert len(store.log()) == 1


def test_stale_generated_views_are_removed(repo: Path):
    store = GitStore(repo)
    store.init()
    intent = Intent(author="alice", problem="x", proposed_outcome="y")
    store.mutate(lambda state: state.intents.update({intent.id: intent}), "backbone: create")
    store.mutate(lambda state: state.intents.pop(intent.id), "backbone: discard")
    assert not (repo / f".backbone/intents/{intent.id}.md").exists()
    assert not store.read().intents


def test_diff_reports_whitespace_and_validates_revisions(repo: Path):
    store = GitStore(repo)
    store.init()
    git(repo, "checkout", "-b", "feature")
    (repo / "bad.txt").write_text("trailing space  \n")
    git(repo, "add", "bad.txt")
    git(repo, "commit", "-m", "whitespace issue")
    result = store.check_diff("main", "feature")
    assert result["ok"] is False
    assert result["changed_paths"] == ["bad.txt"]
    assert "trailing whitespace" in result["detail"]
    assert store.check_diff("main", "main")["ok"] is True
    for revision in ("--output=/tmp/unwanted", "does-not-exist"):
        with pytest.raises(StorageError, match="Git revision"):
            store.check_diff("main", revision)


def test_explicit_sync_pushes_to_local_remote(repo: Path, tmp_path: Path):
    store = GitStore(repo)
    state = store.init()
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    assert not (remote / "refs/heads/main").exists()
    result = store.sync()
    assert result["ok"]
    assert result["branch"] == "main"
    assert git(remote, "rev-parse", "main") == state.version
    with pytest.raises(StorageError, match="Unknown Git remote"):
        store.sync("--force")
    with pytest.raises(StorageError, match="Invalid destination branch"):
        store.sync(branch="main:other")


def test_diff_includes_rename_source_and_destination_for_scope_checks(repo: Path):
    store = GitStore(repo)
    store.init()
    (repo / "protected.py").write_text("def greeting():\n    return 'hello'\n")
    git(repo, "add", "protected.py")
    git(repo, "commit", "-m", "protected source")
    git(repo, "checkout", "-b", "feature")
    git(repo, "mv", "protected.py", "allowed.py")
    git(repo, "commit", "-m", "move protected source")
    result = store.check_diff("main", "feature")
    assert result["changed_paths"] == ["allowed.py", "protected.py"]


def test_store_resolves_subdirectories_and_worktrees(repo: Path, tmp_path: Path):
    store = GitStore(repo)
    store.init()
    nested = repo / "src"
    nested.mkdir()
    assert GitStore(nested).root == repo
    worktree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-b", "parallel", str(worktree))
    other = GitStore(worktree)
    other.mutate(lambda state: state.sessions.update({"parallel": {}}), "backbone: worktree change")
    assert "parallel" in other.read().sessions
    assert "parallel" not in store.read().sessions
    assert git(worktree, "status", "--porcelain") == ""
