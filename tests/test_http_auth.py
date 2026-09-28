"""HTTP authentication exercises role and identity boundaries through real Git state."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backbone_conductor.api import create_app
from backbone_conductor.auth import TokenAuth, create_token_file
from backbone_conductor.cli import main
from backbone_conductor.service import Conductor

ADMIN_TOKEN = "admin-token-" + "a" * 40
ALICE_TOKEN = "alice-token-" + "b" * 40
BOB_TOKEN = "bob-token-" + "c" * 40
CAROL_TOKEN = "reviewer-token-" + "d" * 40


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def credential(name: str, role: str, token: str) -> dict:
    return {"name": name, "role": role, "sha256": hashlib.sha256(token.encode()).hexdigest()}


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Auth Tests")
    git(repo, "config", "user.email", "auth@example.invalid")
    Conductor(repo).initialize()
    auth_file = tmp_path / "credentials.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": [
                    credential("owner", "admin", ADMIN_TOKEN),
                    credential("alice", "member", ALICE_TOKEN),
                    credential("bob", "member", BOB_TOKEN),
                    credential("carol", "reviewer", CAROL_TOKEN),
                ]
            }
        ),
        encoding="utf-8",
    )
    auth_file.chmod(0o600)
    return repo, auth_file


def test_submitted_patch_is_visible_to_reviewer_but_not_member(
    auth_repo: tuple[Path, Path], capsys
) -> None:
    repo, auth_file = auth_repo
    service = Conductor(repo)
    intent = service.create_intent(
        {
            "author": "owner",
            "problem": "Add an export function",
            "proposed_outcome": "Exports are available",
            "affected_paths": ["export.py"],
        }
    )
    service.transition_intent(intent["id"], "accepted")
    task = service.dispatch_task(intent["id"], "alice")
    service.start_task(task["id"], "alice")
    git(repo, "switch", "-c", "feature/export")
    (repo / "export.py").write_text("def export():\n    return []\n")
    git(repo, "add", "export.py")
    git(repo, "commit", "-m", "Implement export")
    git(repo, "switch", "main")
    assert service.submit_artifact(
        "alice",
        {
            "intent_id": intent["id"],
            "branch": "feature/export",
            "base_ref": "main",
            "summary": "Implement export",
        },
    )["accepted"]
    route = f"/tasks/{task['id']}/inspection"
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        assert client.get(route).status_code == 401
        assert client.get(route, headers=auth_header(ALICE_TOKEN)).status_code == 403
        assert client.get(route, headers=auth_header(BOB_TOKEN)).status_code == 403
        for token in (CAROL_TOKEN, ADMIN_TOKEN):
            response = client.get(route, headers=auth_header(token))
            assert response.status_code == 200, response.text
            assert "+def export():" in response.json()["diff"]["patch"]
    assert main(["--repo", str(repo), "task", "inspect", task["id"]]) == 0
    assert "+def export():" in capsys.readouterr().out


def test_http_authenticates_and_limits_member_to_own_tasks(auth_repo: tuple[Path, Path]) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        assert client.get("/health").status_code == 200
        missing = client.get("/state")
        assert missing.status_code == 401
        assert missing.headers["WWW-Authenticate"] == "Bearer"
        assert client.get("/state", headers=auth_header("x" * 40)).status_code == 401
        assert client.get("/state", headers=auth_header(ADMIN_TOKEN)).status_code == 200
        assert client.get("/whoami").status_code == 401
        assert client.get("/whoami", headers=auth_header(ADMIN_TOKEN)).json() == {
            "name": "owner",
            "role": "admin",
        }
        assert client.get("/whoami", headers=auth_header(ALICE_TOKEN)).json() == {
            "name": "alice",
            "role": "member",
        }
        assert client.get("/whoami", headers=auth_header(CAROL_TOKEN)).json() == {
            "name": "carol",
            "role": "reviewer",
        }
        assert client.get("/state", headers=auth_header(ALICE_TOKEN)).status_code == 403
        assert client.post("/refresh", headers=auth_header(ALICE_TOKEN), json={}).status_code == 403
        assert (
            client.post("/reconcile", headers=auth_header(ALICE_TOKEN), json={}).status_code == 403
        )
        assert (
            client.post(
                "/reconcile",
                headers=auth_header(ADMIN_TOKEN),
                json={
                    "local_head": "local",
                    "remote_head": "remote",
                    "author": "alice",
                    "rationale": "Reviewed",
                },
            ).status_code
            == 403
        )
        assert client.post("/refresh", headers=auth_header(ADMIN_TOKEN), json={}).status_code == 409
        assert client.get("/docs", headers=auth_header(ALICE_TOKEN)).status_code == 403
        assert client.get("/schema", headers=auth_header(ALICE_TOKEN)).status_code == 200

        payload = {"problem": "Need export", "proposed_outcome": "Export records"}
        spoof = {**payload, "author": "bob"}
        assert (
            client.post("/intents", headers=auth_header(ALICE_TOKEN), json=spoof).status_code == 403
        )
        assert (
            client.post(
                "/intents",
                headers=auth_header(ALICE_TOKEN),
                json={**payload, "status": "accepted"},
            ).status_code
            == 403
        )
        response = client.post("/intents", headers=auth_header(ALICE_TOKEN), json=payload)
        assert response.status_code == 201, response.text
        intent_id = response.json()["id"]
        assert response.json()["author"] == "alice"
        assert client.get("/intents", headers=auth_header(ALICE_TOKEN)).status_code == 403
        assert (
            client.post(
                f"/intents/{intent_id}/transition",
                headers=auth_header(ALICE_TOKEN),
                json={"status": "accepted"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/intents/{intent_id}/transition",
                headers=auth_header(ADMIN_TOKEN),
                json={"status": "accepted"},
            ).status_code
            == 200
        )
        dispatched = client.post(
            "/tasks",
            headers=auth_header(ADMIN_TOKEN),
            json={"intent_id": intent_id, "member_id": "alice"},
        )
        assert dispatched.status_code == 201, dispatched.text
        task_id = dispatched.json()["id"]
        assert (
            client.get("/tasks", headers=auth_header(ALICE_TOKEN)).json()["tasks"][0]["id"]
            == task_id
        )
        assert client.get("/tasks", headers=auth_header(BOB_TOKEN)).json()["tasks"] == []
        assert client.get(f"/tasks/{task_id}", headers=auth_header(BOB_TOKEN)).status_code == 403
        assert client.get(f"/tasks/{task_id}", headers=auth_header(ALICE_TOKEN)).status_code == 200
        assert (
            client.get(
                "/tasks", params={"member_id": "alice"}, headers=auth_header(BOB_TOKEN)
            ).status_code
            == 403
        )
        assert (
            client.get("/sync", headers=auth_header(ALICE_TOKEN)).json()["updates"][0]["task_id"]
            == task_id
        )
        assert (
            client.get(
                "/sync", params={"member_id": "alice"}, headers=auth_header(BOB_TOKEN)
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/tasks/{task_id}/start",
                headers=auth_header(BOB_TOKEN),
                json={"member_id": "alice"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/tasks/{task_id}/start",
                headers=auth_header(ALICE_TOKEN),
                json={"member_id": "alice"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/artifacts",
                headers=auth_header(BOB_TOKEN),
                json={"member_id": "alice", "artifact": {}},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/tasks/{task_id}/cancel",
                headers=auth_header(ALICE_TOKEN),
                json={"author": "alice", "reason": "stop"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/tasks/{task_id}/cancel",
                headers=auth_header(ADMIN_TOKEN),
                json={"author": "someone-else", "reason": "stop"},
            ).status_code
            == 403
        )
        cancelled = client.post(
            f"/tasks/{task_id}/cancel",
            headers=auth_header(ADMIN_TOKEN),
            json={"author": "owner", "reason": "requirements changed"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["task"]["cancelled_by"] == "owner"
    history = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%B", "--", ".backbone"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Backbone-HTTP-Principal: alice" in history
    assert "Backbone-HTTP-Role: member" in history
    assert "Backbone-HTTP-Principal: owner" in history
    assert "Backbone-HTTP-Role: admin" in history
    assert all(token not in history for token in (ADMIN_TOKEN, ALICE_TOKEN, BOB_TOKEN))
    entries = Conductor(repo).log()
    assert {entry.get("http_principal") for entry in entries} >= {"owner", "alice"}
    assert any(
        entry.get("http_principal") == "owner" and entry.get("http_role") == "admin"
        for entry in entries
    )
    Conductor(repo).create_intent(
        {"id": "intent-local", "author": "local", "problem": "Local", "proposed_outcome": "Work"}
    )
    local_commit = subprocess.run(
        ["git", "-C", str(repo), "show", "-s", "--format=%B", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Backbone-HTTP-" not in local_commit


def test_only_admin_can_replace_intent_with_bound_author(auth_repo: tuple[Path, Path]) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        original = client.post(
            "/intents",
            headers=auth_header(ALICE_TOKEN),
            json={"problem": "Old scope", "proposed_outcome": "Deliver"},
        ).json()
        client.post(
            f"/intents/{original['id']}/transition",
            headers=auth_header(ADMIN_TOKEN),
            json={"status": "accepted"},
        )
        payload = {
            "author": "owner",
            "patch": {"problem": "New scope"},
            "reason": "Priority changed",
            "expected_version": Conductor(repo).state()["version"],
        }
        path = f"/intents/{original['id']}/replace"
        assert client.post(path, headers=auth_header(ALICE_TOKEN), json=payload).status_code == 403
        assert client.post(path, headers=auth_header(CAROL_TOKEN), json=payload).status_code == 403
        assert (
            client.post(
                path, headers=auth_header(ADMIN_TOKEN), json={**payload, "author": "alice"}
            ).status_code
            == 403
        )
        result = client.post(path, headers=auth_header(ADMIN_TOKEN), json=payload)
        assert result.status_code == 201, result.text
        assert result.json()["replacement"]["author"] == "owner"


def test_reviewer_can_review_others_intent_with_bound_identity(
    auth_repo: tuple[Path, Path],
) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        original = client.post(
            "/intents",
            headers=auth_header(ALICE_TOKEN),
            json={"problem": "Need export", "proposed_outcome": "Export records"},
        ).json()
        path = f"/intents/{original['id']}/review"
        payload = {
            "author": "carol",
            "outcome": "accepted",
            "rationale": "The scope is clear",
            "expected_version": Conductor(repo).state()["version"],
        }
        assert client.post(path, headers=auth_header(ALICE_TOKEN), json=payload).status_code == 403
        assert (
            client.post(
                path, headers=auth_header(CAROL_TOKEN), json={**payload, "author": "alice"}
            ).status_code
            == 403
        )
        accepted = client.post(path, headers=auth_header(CAROL_TOKEN), json=payload)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["reviews"][-1]["reviewer"] == "carol"
        assert accepted.json()["reviews"][-1]["reviewed_version"] == payload["expected_version"]
        timeline = client.get("/timeline", headers=auth_header(CAROL_TOKEN))
        assert timeline.status_code == 200
        assert timeline.json()[0]["http_principal"] == "carol"
        assert timeline.json()[0]["http_role"] == "reviewer"
        filtered = client.get(
            "/timeline",
            headers=auth_header(CAROL_TOKEN),
            params={"http_principal": "carol", "event_type": "intent", "limit": 1},
        )
        assert filtered.status_code == 200
        assert len(filtered.json()) == 1
        assert filtered.json()[0]["http_principal"] == "carol"
        assert filtered.json()[0]["event_type"] == "intent"
        older = client.get(
            "/timeline",
            headers=auth_header(CAROL_TOKEN),
            params={"http_principal": "alice", "limit": 1},
        )
        assert older.status_code == 200
        assert len(older.json()) == 1
        assert older.json()[0]["http_principal"] == "alice"
        assert client.get("/timeline", headers=auth_header(ALICE_TOKEN)).status_code == 403
        assert client.get("/audit/verify", headers=auth_header(ALICE_TOKEN)).status_code == 403
        audit = client.get("/audit/verify", headers=auth_header(CAROL_TOKEN))
        assert audit.status_code == 200
        assert audit.json()["unsigned"] >= 1
        assert client.post(path, headers=auth_header(CAROL_TOKEN), json=payload).status_code == 422
        own = Conductor(repo).create_intent(
            {"author": "carol", "problem": "Own scope", "proposed_outcome": "Deliver"}
        )
        own_payload = {**payload, "expected_version": Conductor(repo).state()["version"]}
        assert (
            client.post(
                f"/intents/{own['id']}/review",
                headers=auth_header(CAROL_TOKEN),
                json=own_payload,
            ).status_code
            == 403
        )
    history = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%B", "--", ".backbone"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Backbone-HTTP-Principal: carol" in history
    assert "Backbone-HTTP-Role: reviewer" in history


def test_reviewer_can_approve_integrated_work_but_not_manage_tasks(
    auth_repo: tuple[Path, Path],
) -> None:
    repo, auth_file = auth_repo
    reviewer = auth_header(CAROL_TOKEN)
    admin = auth_header(ADMIN_TOKEN)
    member = auth_header(ALICE_TOKEN)
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        for path in ("/state", "/intents", "/decisions", "/tasks", "/conflicts", "/timeline"):
            assert client.get(path, headers=reviewer).status_code == 200
        for path in ("/initialize", "/tasks", "/conflicts/check", "/refresh", "/sync"):
            assert client.post(path, headers=reviewer, json={}).status_code == 403
        assert client.post("/intents", headers=reviewer, json={}).status_code == 403
        assert client.post("/decisions", headers=reviewer, json={}).status_code == 403
        assert client.post("/reconcile", headers=reviewer, json={}).status_code == 403

        created = client.post(
            "/intents",
            headers=member,
            json={
                "id": "intent-review",
                "problem": "Need a reviewed feature",
                "proposed_outcome": "Add the feature",
                "affected_paths": ["feature.py"],
            },
        )
        assert created.status_code == 201, created.text
        assert client.get("/intents/intent-review", headers=reviewer).status_code == 200
        assert (
            client.post(
                "/intents/intent-review/transition",
                headers=reviewer,
                json={"status": "accepted"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/intents/intent-review/transition",
                headers=admin,
                json={"status": "accepted"},
            ).status_code
            == 200
        )
        dispatched = client.post(
            "/tasks", headers=admin, json={"intent_id": "intent-review", "member_id": "alice"}
        )
        assert dispatched.status_code == 201, dispatched.text
        task_id = dispatched.json()["id"]
        assert client.get(f"/tasks/{task_id}", headers=reviewer).status_code == 200
        assert (
            client.post(
                f"/tasks/{task_id}/start", headers=member, json={"member_id": "alice"}
            ).status_code
            == 200
        )

        git(repo, "switch", "-c", "review-feature")
        (repo / "feature.py").write_text("def feature():\n    return True\n", encoding="utf-8")
        git(repo, "add", "feature.py")
        git(repo, "commit", "-m", "Add reviewed feature")
        git(repo, "switch", "main")
        submitted = client.post(
            f"/tasks/{task_id}/submit",
            headers=member,
            json={
                "member_id": "alice",
                "artifact": {
                    "branch": "review-feature",
                    "base_ref": "main",
                    "summary": "Added feature",
                },
            },
        )
        assert submitted.status_code == 200, submitted.text
        git(repo, "merge", "--no-edit", "review-feature")
        packet = client.get(f"/tasks/{task_id}/inspection", headers=reviewer).json()
        anchor = {
            "expected_version": packet["version"],
            "expected_target_sha": packet["git"]["target_sha"],
        }
        assert (
            client.post(
                f"/tasks/{task_id}/merge",
                headers=reviewer,
                json={"author": "carol", **anchor},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/tasks/{task_id}/merge",
                headers=reviewer,
                json={"author": "owner", "rationale": "Reviewed feature and constraints", **anchor},
            ).status_code
            == 403
        )
        approved = client.post(
            f"/tasks/{task_id}/merge",
            headers=reviewer,
            json={"author": "carol", "rationale": "Reviewed feature and constraints", **anchor},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["review_decision"]["author"] == "carol"
        assert approved.json()["task"]["status"] == "merged"

        another = client.post(
            "/intents",
            headers=admin,
            json={"id": "intent-self", "problem": "Self review", "proposed_outcome": "Avoid it"},
        )
        assert another.status_code == 201
        assert (
            client.post(
                "/intents/intent-self/transition", headers=admin, json={"status": "accepted"}
            ).status_code
            == 200
        )
        own_task = client.post(
            "/tasks", headers=admin, json={"intent_id": "intent-self", "member_id": "carol"}
        )
        assert own_task.status_code == 201
        assert (
            client.post(
                f"/tasks/{own_task.json()['id']}/merge",
                headers=reviewer,
                json={
                    "author": "carol",
                    "rationale": "Cannot approve my own assignment",
                    "expected_version": client.get("/state", headers=reviewer).json()["version"],
                    "expected_target_sha": "0" * 40,
                },
            ).status_code
            == 403
        )

    history = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%B", "--", ".backbone"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Backbone-HTTP-Principal: carol" in history
    assert "Backbone-HTTP-Role: reviewer" in history


def test_reviewer_can_arbitrate_with_bound_identity(auth_repo: tuple[Path, Path]) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        for intent_id, token in (("intent-left", ALICE_TOKEN), ("intent-right", BOB_TOKEN)):
            response = client.post(
                "/intents",
                headers=auth_header(token),
                json={
                    "id": intent_id,
                    "problem": "Competing change",
                    "proposed_outcome": "Change shared path",
                    "affected_paths": ["shared.py"],
                },
            )
            assert response.status_code == 201, response.text
            assert (
                client.post(
                    f"/intents/{intent_id}/transition",
                    headers=auth_header(ADMIN_TOKEN),
                    json={"status": "accepted"},
                ).status_code
                == 200
            )
        checked = client.post("/conflicts/check", headers=auth_header(ADMIN_TOKEN))
        assert checked.status_code == 200, checked.text
        conflicts = client.get("/conflicts", headers=auth_header(CAROL_TOKEN)).json()
        assert conflicts
        conflict_id = conflicts[0]["id"]
        spoof = client.post(
            f"/conflicts/{conflict_id}/resolve",
            headers=auth_header(CAROL_TOKEN),
            json={"author": "owner", "action": "coordinate", "rationale": "Reviewed both scopes"},
        )
        assert spoof.status_code == 403
        resolved = client.post(
            f"/conflicts/{conflict_id}/resolve",
            headers=auth_header(CAROL_TOKEN),
            json={"author": "carol", "action": "coordinate", "rationale": "Reviewed both scopes"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["decision"]["author"] == "carol"
        assert resolved.json()["conflict"]["resolved"] is True
    latest = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%B", "--", ".backbone"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Backbone-HTTP-Principal: carol" in latest
    assert "Backbone-HTTP-Role: reviewer" in latest


def test_member_decisions_and_admin_author_are_bound(auth_repo: tuple[Path, Path]) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        payload = {"decision_type": "architecture", "summary": "Use JSON", "rationale": "Portable"}
        assert (
            client.post(
                "/decisions", headers=auth_header(ALICE_TOKEN), json={**payload, "author": "bob"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/decisions",
                headers=auth_header(ALICE_TOKEN),
                json={**payload, "status": "accepted"},
            ).status_code
            == 403
        )
        created = client.post("/decisions", headers=auth_header(ALICE_TOKEN), json=payload)
        assert created.status_code == 201
        assert created.json()["author"] == "alice"
        assert (
            client.post(
                "/intents",
                headers=auth_header(ADMIN_TOKEN),
                json={"author": "bob", "problem": "x", "proposed_outcome": "y"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/decisions/{created.json()['id']}/transition",
                headers=auth_header(ALICE_TOKEN),
                json={"status": "accepted"},
            ).status_code
            == 403
        )


def test_credential_file_is_private_and_outside_git(auth_repo: tuple[Path, Path]) -> None:
    repo, auth_file = auth_repo
    auth = TokenAuth(auth_file, repo)
    assert auth.authenticate(f"Bearer {ADMIN_TOKEN}").name == "owner"
    assert auth.authenticate(f"Bearer {ALICE_TOKEN}").role == "member"
    assert auth.authenticate("Basic abc") is None
    assert auth.authenticate("Bearer short") is None
    auth_file.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        TokenAuth(auth_file, repo)
    auth_file.chmod(0o600)
    inside = repo / "tokens.json"
    inside.write_text(auth_file.read_text())
    inside.chmod(0o600)
    with pytest.raises(ValueError, match="outside the repository"):
        TokenAuth(inside, repo)
    config = json.loads(auth_file.read_text())
    config["tokens"].append(config["tokens"][0])
    auth_file.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="unique"):
        TokenAuth(auth_file, repo)
    config["tokens"][-1] = credential("carol", "reviewer", "another-token-" + "x" * 40)
    auth_file.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="principal names must be unique"):
        TokenAuth(auth_file, repo)


def test_non_loopback_serve_requires_auth_file(auth_repo: tuple[Path, Path], capsys) -> None:
    repo, _ = auth_repo
    assert main(["--repo", str(repo), "serve", "--host", "0.0.0.0"]) == 1
    assert "--auth-file" in json.loads(capsys.readouterr().err)["error"]


@pytest.mark.parametrize("option", ["--tls-certfile", "--tls-keyfile"])
def test_direct_https_requires_certificate_and_key(
    auth_repo: tuple[Path, Path], capsys, option: str
) -> None:
    repo, auth_file = auth_repo
    assert main(["--repo", str(repo), "serve", "--auth-file", str(auth_file), option, "x"]) == 1
    assert "requires both" in json.loads(capsys.readouterr().err)["error"]


def test_direct_https_rejects_unsafe_private_key(auth_repo: tuple[Path, Path], capsys) -> None:
    repo, auth_file = auth_repo
    prefix = [
        "--repo",
        str(repo),
        "serve",
        "--auth-file",
        str(auth_file),
        "--tls-certfile",
        str(repo.parent / "cert.pem"),
        "--tls-keyfile",
    ]
    inside = repo / "key.pem"
    inside.write_text("test", encoding="utf-8")
    inside.chmod(0o600)
    assert main([*prefix, str(inside)]) == 1
    assert "outside the repository" in json.loads(capsys.readouterr().err)["error"]

    outside = repo.parent / "key.pem"
    outside.write_text("test", encoding="utf-8")
    outside.chmod(0o644)
    assert main([*prefix, str(outside)]) == 1
    assert "0600" in json.loads(capsys.readouterr().err)["error"]

    outside.chmod(0o600)
    link = repo.parent / "key-link.pem"
    link.symlink_to(outside)
    assert main([*prefix, str(link)]) == 1
    assert "symlink" in json.loads(capsys.readouterr().err)["error"]


def test_token_file_creation_is_private_and_does_not_store_plaintext(
    auth_repo: tuple[Path, Path], tmp_path: Path, capsys
) -> None:
    repo, _ = auth_repo
    output = tmp_path / "issued.json"
    assert (
        main(
            [
                "--repo",
                str(repo),
                "auth",
                "create",
                "--file",
                str(output),
                "--admin",
                "owner",
                "--member",
                "alice",
                "--reviewer",
                "carol",
            ]
        )
        == 0
    )
    issued = json.loads(capsys.readouterr().out)["credentials"]
    assert len(issued) == 3
    assert output.stat().st_mode & 0o777 == 0o600
    assert all(item["token"] not in output.read_text() for item in issued)
    auth = TokenAuth(output, repo)
    assert auth.authenticate(f"Bearer {issued[0]['token']}").role == "admin"
    assert auth.authenticate(f"Bearer {issued[1]['token']}").name == "alice"
    assert auth.authenticate(f"Bearer {issued[2]['token']}").role == "reviewer"
    with pytest.raises(FileExistsError):
        create_token_file(output, repo, "owner", [])
    assert (
        main(
            [
                "--repo",
                str(repo),
                "auth",
                "create",
                "--file",
                str(repo / "auth.json"),
                "--admin",
                "owner",
            ]
        )
        == 1
    )
    assert not (repo / "auth.json").exists()
    capsys.readouterr()
    with pytest.raises(ValueError, match="unique"):
        create_token_file(tmp_path / "duplicate.json", repo, "alice", ["alice"])
    with pytest.raises(ValueError, match="unique"):
        create_token_file(tmp_path / "duplicate-reviewer.json", repo, "owner", [], ["owner"])


def test_http_tokens_rotate_without_restart_and_fail_closed(
    auth_repo: tuple[Path, Path], capsys
) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        assert client.get("/state", headers=auth_header(ADMIN_TOKEN)).status_code == 200
        assert client.get("/state", headers=auth_header(CAROL_TOKEN)).status_code == 200
        assert (
            main(
                [
                    "--repo",
                    str(repo),
                    "auth",
                    "rotate",
                    "--file",
                    str(auth_file),
                    "--admin",
                    "owner",
                    "--member",
                    "alice",
                    "--reviewer",
                    "carol",
                ]
            )
            == 0
        )
        issued = json.loads(capsys.readouterr().out)["credentials"]
        assert len(issued) == 3
        assert auth_file.stat().st_mode & 0o777 == 0o600
        assert all(item["token"] not in auth_file.read_text() for item in issued)
        assert client.get("/state", headers=auth_header(ADMIN_TOKEN)).status_code == 401
        assert client.get("/tasks", headers=auth_header(BOB_TOKEN)).status_code == 401
        assert client.get("/state", headers=auth_header(CAROL_TOKEN)).status_code == 401
        new_admin = auth_header(issued[0]["token"])
        assert client.get("/state", headers=new_admin).status_code == 200
        assert client.get("/tasks", headers=auth_header(issued[1]["token"])).status_code == 200
        assert client.get("/state", headers=auth_header(issued[2]["token"])).status_code == 200
        auth_file.chmod(0o644)
        assert client.get("/state", headers=new_admin).status_code == 503
        assert client.get("/health").status_code == 503
        auth_file.chmod(0o600)
        assert client.get("/state", headers=new_admin).status_code == 200
        valid_content = auth_file.read_text()
        auth_file.write_text("{invalid json", encoding="utf-8")
        assert client.get("/state", headers=new_admin).status_code == 503
        auth_file.write_text(valid_content, encoding="utf-8")
        assert client.get("/state", headers=new_admin).status_code == 200
        assert (
            main(
                [
                    "--repo",
                    str(repo),
                    "auth",
                    "rotate",
                    "--file",
                    str(auth_file),
                    "--admin",
                    "owner",
                    "--member",
                    "owner",
                ]
            )
            == 1
        )
        capsys.readouterr()
        assert client.get("/state", headers=new_admin).status_code == 200
        replacement = auth_file.with_name("replacement.json")
        replacement.write_text(valid_content, encoding="utf-8")
        replacement.chmod(0o600)
        auth_file.unlink()
        auth_file.symlink_to(replacement)
        assert client.get("/state", headers=new_admin).status_code == 503
        auth_file.unlink()
        os.mkfifo(auth_file, mode=0o600)
        assert client.get("/state", headers=new_admin).status_code == 503
        auth_file.unlink()
        assert client.get("/state", headers=new_admin).status_code == 503
        assert client.get("/health").status_code == 503
