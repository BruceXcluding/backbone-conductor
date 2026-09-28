"""Regression cases identified by an independent final service/interface audit."""

import hashlib
import subprocess

import pytest

from backbone_conductor.service import Conductor


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def audit_project(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Audit Test")
    git(tmp_path, "config", "user.email", "audit@example.invalid")
    (tmp_path / "README.md").write_text("Test project\n")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "Initial commit")
    service = Conductor(tmp_path)
    service.initialize()
    return service, tmp_path


def prepare_artifact(service, repo):
    intent = service.create_intent(
        {
            "author": "owner",
            "problem": "Need a database client",
            "proposed_outcome": "Implement the database client",
            "affected_symbols": ["database"],
            "affected_paths": ["database.py"],
        }
    )
    service.transition_intent(intent["id"], "accepted")
    task = service.dispatch_task(intent["id"], "alice")
    service.start_task(task["id"], "alice")
    git(repo, "switch", "-c", "feature/database")
    (repo / "database.py").write_text("DATABASE = {}\n")
    git(repo, "add", "database.py")
    git(repo, "commit", "-m", "Add database client")
    git(repo, "switch", "main")
    return (
        intent,
        task,
        {
            "intent_id": intent["id"],
            "branch": "feature/database",
            "base_ref": "main",
            "summary": "Add database client",
        },
    )


def test_merge_approval_must_be_recorded_on_assigned_base_branch(audit_project):
    service, repo = audit_project
    intent, task, artifact = prepare_artifact(service, repo)
    assert service.submit_artifact("alice", artifact)["accepted"]
    git(repo, "merge", "--no-edit", "feature/database")
    git(repo, "switch", "-c", "unrelated-work")
    before = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="base|target|branch"):
        service.merge_task(task["id"], "reviewer")
    assert git(repo, "rev-parse", "HEAD") == before
    assert service.state()["intents"][intent["id"]]["status"] == "in_progress"
    git(repo, "switch", "main")
    assert service.merge_task(task["id"], "reviewer")["task"]["status"] == "merged"


def test_review_packet_is_pinned_to_submitted_diff_and_read_only(audit_project):
    service, repo = audit_project
    _intent, task, artifact = prepare_artifact(service, repo)
    with pytest.raises(ValueError, match="submitted"):
        service.inspect_task(task["id"])
    submitted = service.submit_artifact("alice", artifact)
    assert submitted["accepted"]
    state_before = service.state()
    head_before = git(repo, "rev-parse", "HEAD")
    packet = service.inspect_task(task["id"])
    pinned_sha = submitted["artifact"]["commit_sha"]
    assert packet["version"] == state_before["version"]
    assert packet["git"]["artifact_sha"] == pinned_sha
    assert packet["git"]["branch_unchanged"] is True
    assert packet["git"]["integrated_into_target"] is False
    assert packet["diff"]["changed_paths"] == ["database.py"]
    assert "+DATABASE = {}" in packet["diff"]["patch"]
    assert packet["diff"]["truncated"] is False
    assert packet["diff"]["sha256"] == hashlib.sha256(packet["diff"]["patch"].encode()).hexdigest()
    assert packet["requires_human_review"] is True
    assert service.state() == state_before
    assert git(repo, "rev-parse", "HEAD") == head_before

    git(repo, "switch", "feature/database")
    (repo / "database.py").write_text("DATABASE = {'changed': True}\n")
    git(repo, "add", "database.py")
    git(repo, "commit", "-m", "Change after submission")
    git(repo, "switch", "main")
    changed = service.inspect_task(task["id"])
    assert changed["git"]["branch_unchanged"] is False
    assert changed["git"]["artifact_sha"] == pinned_sha
    assert changed["diff"]["patch"] == packet["diff"]["patch"]


@pytest.mark.parametrize("line_count,too_large", [(12_000, False), (60_000, True)])
def test_review_packet_bounds_remote_patch_size(audit_project, line_count, too_large):
    service, repo = audit_project
    _intent, task, artifact = prepare_artifact(service, repo)
    git(repo, "switch", "feature/database")
    (repo / "database.py").write_text(
        "DATABASE = {\n"
        + "".join(f"    'entry-{index:06d}': {index},\n" for index in range(line_count))
        + "}\n"
    )
    git(repo, "add", "database.py")
    git(repo, "commit", "-m", "Expand database fixture")
    git(repo, "switch", "main")
    assert service.submit_artifact("alice", artifact)["accepted"]
    if too_large:
        with pytest.raises(ValueError, match="1 MB review limit"):
            service.inspect_task(task["id"])
    else:
        packet = service.inspect_task(task["id"])
        assert packet["diff"]["truncated"] is True
        assert len(packet["diff"]["patch"].encode()) <= 131_072
        full = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--binary",
                f"{packet['git']['base_sha']}...{packet['git']['artifact_sha']}",
                "--",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert packet["diff"]["sha256"] == hashlib.sha256(full.encode()).hexdigest()


def test_global_dependency_conflict_blocks_artifact_until_human_arbitration(audit_project):
    service, repo = audit_project
    dependent = service.log_decision(
        {
            "author": "owner",
            "decision_type": "storage",
            "summary": "Database client requires database",
            "rationale": "Persist records",
            "depends_on": ["database"],
        }
    )
    service.transition_decision(dependent["id"], "accepted")
    removing = service.log_decision(
        {
            "author": "owner",
            "decision_type": "storage",
            "summary": "Remove database",
            "rationale": "Use stateless storage",
            "removes_symbols": ["database"],
        }
    )
    service.transition_decision(removing["id"], "accepted")
    _, task, artifact = prepare_artifact(service, repo)
    result = service.submit_artifact("alice", artifact)
    assert not result["accepted"]
    assert result["checks"]["decisions"]["status"] == "failed"
    assert service.state()["tasks"][task["id"]]["status"] == "in_progress"
    conflict = next(
        value
        for value in service.state()["conflicts"].values()
        if value["rule"] == "dependency_conflict"
    )
    service.resolve_conflict(conflict["id"], "owner", "accept_risk", "Staged migration is reviewed")
    assert not service.submit_artifact("alice", artifact)["accepted"]
    service.rebase_task(task["id"], "alice", service.state()["version"])
    assert service.submit_artifact("alice", artifact)["accepted"]
