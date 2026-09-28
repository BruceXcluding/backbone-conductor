"""Regression cases identified by an independent final service/interface audit."""

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
