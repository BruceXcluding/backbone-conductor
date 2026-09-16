import subprocess

import pytest

from backbone_conductor.service import Conductor


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def project(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test User")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "README.md").write_text("# Test project\n")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "Initial source")
    service = Conductor(tmp_path)
    service.initialize()
    return service, tmp_path


def assigned(service, **extra):
    intent = service.create_intent(
        {
            "author": "owner",
            "problem": "No greeting",
            "proposed_outcome": "Implement greeting",
            **extra,
        }
    )
    service.transition_intent(intent["id"], "accepted")
    task = service.dispatch_task(intent["id"], "alice", forbidden_paths=["secrets/"])
    service.start_task(task["id"], "alice")
    return intent, task


def feature(repo, path="greeting.py", content="def hello():\n    return 'hello'\n"):
    git(repo, "switch", "-c", "feature/greeting")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Implement greeting")
    commit = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "main")
    return commit


def submission(service, intent, **extra):
    return service.submit_artifact(
        "alice",
        {
            "intent_id": intent["id"],
            "branch": "feature/greeting",
            "summary": "Implemented greeting",
            **extra,
        },
    )


def test_complete_workflow_survives_restart_and_records_human_review(project):
    service, repo = project
    intent, task = assigned(service, affected_paths=["greeting.py"])
    commit = feature(repo)
    result = submission(service, intent, changed_paths=["fake.py"], checks={"code": "passed"})
    assert result["accepted"] and result["requires_human_review"]
    assert result["artifact"]["changed_paths"] == ["greeting.py"]
    assert result["artifact"]["commit_sha"] == commit
    assert result["checks"]["intent"]["status"] == "requires_human_review"
    with pytest.raises(ValueError, match="Merge the reviewed"):
        service.merge_task(task["id"], "owner")
    git(repo, "merge", "--no-edit", "feature/greeting")
    result = service.merge_task(task["id"], "owner")
    assert result["task"]["status"] == "merged"
    restored = Conductor(repo).state()
    assert restored["intents"][intent["id"]]["status"] == "completed"
    assert result["review_decision"]["id"] in restored["decisions"]
    assert service.get_my_task("alice")["tasks"] == []


@pytest.mark.parametrize(
    "path,content,gate",
    [
        ("secrets/token.txt", "secret\n", "scope"),
        ("elsewhere.py", "ok\n", "scope"),
        ("greeting.py", "trailing spaces   \n", "code"),
        (".backbone/rogue.txt", "rewrite metadata\n", "code"),
    ],
)
def test_failed_checks_do_not_advance_task(project, path, content, gate):
    service, repo = project
    intent, task = assigned(service, affected_paths=["greeting.py"])
    feature(repo, path, content)
    result = submission(service, intent)
    assert not result["accepted"]
    assert result["checks"][gate]["status"] == "failed"
    assert service.state()["tasks"][task["id"]]["status"] == "in_progress"


def test_member_and_lifecycle_enforcement(project):
    service, repo = project
    intent, task = assigned(service)
    with pytest.raises(PermissionError):
        service.start_task(task["id"], "mallory")
    with pytest.raises(PermissionError):
        submission(service, intent, member_id="mallory")
    with pytest.raises(ValueError):
        service.transition_intent(intent["id"], "completed")
    with pytest.raises(ValueError):
        service.create_intent(
            {"author": "alice", "problem": "x", "proposed_outcome": "y", "status": "accepted"}
        )
    with pytest.raises(ValueError):
        service.dispatch_task(intent["id"], "bob")
    with pytest.raises(ValueError):
        service.transition_intent(intent["id"], "superseded")
    feature(repo)
    with pytest.raises(ValueError, match="assigned target"):
        submission(service, intent, base_ref="feature/greeting")
    with pytest.raises(ValueError, match="separate"):
        submission(service, intent, branch="main")


def test_branch_change_invalidates_submission(project):
    service, repo = project
    intent, task = assigned(service)
    feature(repo)
    assert submission(service, intent)["accepted"]
    git(repo, "switch", "feature/greeting")
    (repo / "additional.py").write_text("# Not reviewed\n")
    git(repo, "add", "additional.py")
    git(repo, "commit", "-m", "Change after submission")
    git(repo, "switch", "main")
    git(repo, "merge", "--no-edit", "feature/greeting")
    with pytest.raises(ValueError, match="changed after"):
        service.merge_task(task["id"], "owner")


def test_arbitration_is_audited_and_new_evidence_is_not_waived(project):
    service, repo = project
    intent, task = assigned(
        service, affected_symbols=["Greeting"], operations={"Greeting": "extend"}
    )
    other = service.create_intent(
        {
            "author": "bob",
            "problem": "Remove old API",
            "proposed_outcome": "Remove it",
            "affected_symbols": ["Greeting"],
            "operations": {"Greeting": "remove"},
        }
    )
    service.transition_intent(other["id"], "accepted")
    feature(repo)
    result = submission(service, intent)
    assert not result["accepted"]
    conflict = next(c for c in result["conflicts"] if c["severity"] != "advisory")
    resolution = service.resolve_conflict(
        conflict["id"], "owner", "coordinate", "Keep compatibility until next release"
    )
    assert resolution["decision"]["status"] == "accepted"
    assert submission(service, intent)["accepted"]
    assert service.detect_conflicts()["blocking"] == 0
    with pytest.raises(ValueError, match="already resolved"):
        service.resolve_conflict(conflict["id"], "owner", "coordinate", "Again")


def test_decision_supersession_and_task_sync(project):
    service, _ = project
    _, task = assigned(service)
    first = service.log_decision(
        {"author": "owner", "decision_type": "storage", "summary": "Use Git", "rationale": "Audit"}
    )
    service.transition_decision(first["id"], "accepted")
    updates = service.check_backbone_sync("alice")
    assert first["id"] in updates["updates"][0]["new_decisions"]
    second = service.log_decision(
        {
            "author": "owner",
            "decision_type": "storage",
            "summary": "Use Git and cache",
            "rationale": "Speed",
            "supersedes": first["id"],
        }
    )
    service.transition_decision(second["id"], "accepted")
    assert service.state()["decisions"][first["id"]]["status"] == "superseded"
    service.transition_decision(second["id"], "reverted")
    state = service.state()
    assert not service.check_backbone_sync("alice", state["version"])["changed"]
    assert task["id"] in state["tasks"]


def test_advisory_semantic_review_and_stale_review_rejected(project, monkeypatch):
    from backbone_conductor.runtime import DSHReviewer

    service, repo = project
    intent, task = assigned(service)
    feature(repo)
    submission(service, intent)
    monkeypatch.setattr(
        DSHReviewer,
        "review",
        lambda *args: {"verdict": "aligned", "rationale": "Meets task", "concerns": []},
    )
    review = service.review_task(task["id"], str(repo / "dsh-home"), "test-model")
    assert review["advisory"]
    assert service.state()["tasks"][task["id"]]["status"] == "submitted"

    def stale(*args):
        service.detect_conflicts()
        return {"verdict": "aligned", "rationale": "Meets task", "concerns": []}

    monkeypatch.setattr(DSHReviewer, "review", stale)
    with pytest.raises(ValueError, match="changed during"):
        service.review_task(task["id"], str(repo / "dsh-home"), "test-model")
