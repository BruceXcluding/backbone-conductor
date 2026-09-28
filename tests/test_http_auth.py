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
                ]
            }
        ),
        encoding="utf-8",
    )
    auth_file.chmod(0o600)
    return repo, auth_file


def test_http_authenticates_and_limits_member_to_own_tasks(auth_repo: tuple[Path, Path]) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        assert client.get("/health").status_code == 200
        missing = client.get("/state")
        assert missing.status_code == 401
        assert missing.headers["WWW-Authenticate"] == "Bearer"
        assert client.get("/state", headers=auth_header("x" * 40)).status_code == 401
        assert client.get("/state", headers=auth_header(ADMIN_TOKEN)).status_code == 200
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


def test_non_loopback_serve_requires_auth_file(auth_repo: tuple[Path, Path], capsys) -> None:
    repo, _ = auth_repo
    assert main(["--repo", str(repo), "serve", "--host", "0.0.0.0"]) == 1
    assert "--auth-file" in json.loads(capsys.readouterr().err)["error"]


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
            ]
        )
        == 0
    )
    issued = json.loads(capsys.readouterr().out)["credentials"]
    assert len(issued) == 2
    assert output.stat().st_mode & 0o777 == 0o600
    assert all(item["token"] not in output.read_text() for item in issued)
    auth = TokenAuth(output, repo)
    assert auth.authenticate(f"Bearer {issued[0]['token']}").role == "admin"
    assert auth.authenticate(f"Bearer {issued[1]['token']}").name == "alice"
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


def test_http_tokens_rotate_without_restart_and_fail_closed(
    auth_repo: tuple[Path, Path], capsys
) -> None:
    repo, auth_file = auth_repo
    with TestClient(create_app(repo, auth_file=auth_file)) as client:
        assert client.get("/state", headers=auth_header(ADMIN_TOKEN)).status_code == 200
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
                ]
            )
            == 0
        )
        issued = json.loads(capsys.readouterr().out)["credentials"]
        assert len(issued) == 2
        assert auth_file.stat().st_mode & 0o777 == 0o600
        assert all(item["token"] not in auth_file.read_text() for item in issued)
        assert client.get("/state", headers=auth_header(ADMIN_TOKEN)).status_code == 401
        assert client.get("/tasks", headers=auth_header(BOB_TOKEN)).status_code == 401
        new_admin = auth_header(issued[0]["token"])
        assert client.get("/state", headers=new_admin).status_code == 200
        assert client.get("/tasks", headers=auth_header(issued[1]["token"])).status_code == 200
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
