"""Exercise real Git ledgers through CLI, HTTP, and the MCP wire protocol."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from backbone_conductor.api import create_app
from backbone_conductor.cli import main
from backbone_conductor.mcp_server import create_server
from backbone_conductor.service import Conductor

SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def interface_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Interface Tests")
    git(repo, "config", "user.email", "interfaces@example.invalid")
    (repo / "README.md").write_text("Interface test project\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Initial project")
    return repo


def intent_data() -> dict:
    return {
        "author": "alice",
        "problem": "A project needs an export function",
        "proposed_outcome": "Add a deterministic export function",
        "affected_symbols": ["export"],
        "affected_paths": ["export.py"],
    }


def test_cli_initialization_creation_and_readable_failures(interface_repo: Path, capsys) -> None:
    prefix = ["--repo", str(interface_repo)]
    assert main([*prefix, "init"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    # Inputs stay outside the repository so they do not alter the user's worktree.
    payload = interface_repo.parent / "intent.json"
    payload.write_text(json.dumps(intent_data()), encoding="utf-8")
    assert main([*prefix, "intent", "create", "--file", str(payload)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["author"] == "alice"
    assert main([*prefix, "intent", "transition", created["id"], "completed"]) == 1
    error = capsys.readouterr()
    assert error.out == ""
    assert "error" in json.loads(error.err)
    assert main([*prefix, "intent", "transition", "missing", "accepted"]) == 1
    assert "missing" in json.loads(capsys.readouterr().err)["error"]
    assert main([*prefix, "log", "--limit", "0"]) == 1
    assert "limit" in json.loads(capsys.readouterr().err)["error"]


def test_cli_rejects_non_object_json_and_exports_schema(interface_repo: Path, capsys) -> None:
    payload = interface_repo.parent / "invalid.json"
    payload.write_text("[]", encoding="utf-8")
    assert main(["--repo", str(interface_repo), "intent", "create", "--file", str(payload)]) == 1
    assert "object" in json.loads(capsys.readouterr().err)["error"]
    assert main(["schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert "Intent" in schema["$defs"]
    assert "tasks" in schema["properties"]


def test_python_module_propagates_failure_exit_code(interface_repo: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backbone_conductor",
            "--repo",
            str(interface_repo),
            "log",
            "--limit",
            "0",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        env={**os.environ, "PYTHONPATH": SOURCE_ROOT},
    )
    assert result.returncode == 1
    assert "limit" in json.loads(result.stderr)["error"]
    assert result.stdout == ""


def test_http_lifecycle_and_error_mapping(interface_repo: Path) -> None:
    with TestClient(create_app(interface_repo)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/initialize").status_code == 200
        invalid = client.post("/intents", json={"author": "alice"})
        assert invalid.status_code == 422
        response = client.post("/intents", json=intent_data())
        assert response.status_code == 201
        intent_id = response.json()["id"]
        assert client.get("/intents/missing").status_code == 404
        assert client.get(f"/intents/{intent_id}").json()["status"] == "draft"
        response = client.post(f"/intents/{intent_id}/transition", json={"status": "completed"})
        assert response.status_code == 422
        assert (
            client.post(f"/intents/{intent_id}/transition", json={"status": "accepted"}).status_code
            == 200
        )
        task = client.post("/tasks", json={"intent_id": intent_id, "member_id": "alice"})
        assert task.status_code == 201
        task_id = task.json()["id"]
        assert client.get("/tasks", params={"member_id": "bob"}).json()["tasks"] == []
        assert client.post(f"/tasks/{task_id}/start", json={"member_id": "bob"}).status_code == 403
        assert (
            client.post(f"/tasks/{task_id}/start", json={"member_id": "alice"}).status_code == 200
        )
        assert client.get("/tasks").json()["tasks"][0]["status"] == "in_progress"
        assert client.get("/timeline", params={"limit": 0}).status_code == 422
        assert len(client.get("/timeline").json()) >= 4
        assert client.get("/schema").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_http_task_submission_binds_path_and_requires_real_merge(interface_repo: Path) -> None:
    conductor = Conductor(interface_repo)
    conductor.initialize()
    intent = conductor.create_intent(intent_data())
    conductor.transition_intent(intent["id"], "accepted")
    task = conductor.dispatch_task(intent["id"], "alice")
    conductor.start_task(task["id"], "alice")
    git(interface_repo, "switch", "-c", "member-export")
    (interface_repo / "export.py").write_text("def export():\n    return []\n", encoding="utf-8")
    git(interface_repo, "add", "export.py")
    git(interface_repo, "commit", "-m", "Add export")
    git(interface_repo, "switch", "main")
    payload = {
        "member_id": "alice",
        "artifact": {"branch": "member-export", "base_ref": "main", "summary": "Added export"},
    }
    with TestClient(create_app(interface_repo)) as client:
        mismatch = {**payload, "artifact": {**payload["artifact"], "intent_id": "wrong"}}
        assert client.post(f"/tasks/{task['id']}/submit", json=mismatch).status_code == 422
        spoof = {**payload, "member_id": "bob"}
        assert client.post(f"/tasks/{task['id']}/submit", json=spoof).status_code == 403
        result = client.post(f"/tasks/{task['id']}/submit", json=payload)
        assert result.status_code == 200, result.text
        assert (
            client.post(f"/tasks/{task['id']}/merge", json={"author": "reviewer"}).status_code
            == 422
        )
        git(interface_repo, "merge", "--no-edit", "member-export")
        approved = client.post(f"/tasks/{task['id']}/merge", json={"author": "reviewer"})
        assert approved.status_code == 200, approved.text
        assert client.get(f"/intents/{intent['id']}").json()["status"] == "completed"


def test_mcp_member_binding_hides_admin_and_rejects_spoofing(interface_repo: Path) -> None:
    Conductor(interface_repo).initialize()

    async def check() -> None:
        server = create_server(interface_repo, "alice")
        names = {tool.name for tool in await server.list_tools()}
        assert {
            "get_my_task",
            "submit_artifact",
            "check_backbone_sync",
            "create_intent",
            "log_decision",
        } <= names
        assert not {"dispatch_task", "transition_intent", "resolve_conflict", "merge_task"} & names
        with pytest.raises(ToolError, match="bound member"):
            await server.call_tool("get_my_task", {"member_id": "bob"})
        with pytest.raises(ToolError, match="bound member"):
            await server.call_tool(
                "create_intent", {"intent_data": {**intent_data(), "author": "bob"}}
            )
        with pytest.raises(ToolError, match="draft"):
            await server.call_tool(
                "create_intent", {"intent_data": {**intent_data(), "status": "accepted"}}
            )
        data = intent_data()
        del data["author"]
        await server.call_tool("create_intent", {"intent_data": data})
        state = Conductor(interface_repo).state()
        assert next(iter(state["intents"].values()))["author"] == "alice"
        admin_names = {tool.name for tool in await create_server(interface_repo).list_tools()}
        assert {
            "dispatch_task",
            "transition_intent",
            "resolve_conflict",
            "merge_task",
        } <= admin_names

    asyncio.run(check())


def test_mcp_stdio_protocol_roundtrip(interface_repo: Path) -> None:
    Conductor(interface_repo).initialize()

    async def check() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "backbone_conductor",
                "--repo",
                str(interface_repo),
                "mcp",
                "--member",
                "alice",
            ],
            env={"PYTHONPATH": SOURCE_ROOT},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert "get_my_task" in {tool.name for tool in listed.tools}
            result = await session.call_tool("get_my_task", {})
            assert not result.isError
            parsed = json.loads(result.content[0].text)
            assert parsed["member_id"] == "alice"
            assert parsed["tasks"] == []
            denied = await session.call_tool("get_my_task", {"member_id": "bob"})
            assert denied.isError

    asyncio.run(asyncio.wait_for(check(), timeout=20))
