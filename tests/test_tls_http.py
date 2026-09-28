"""Verify that direct TLS serves authenticated HTTP with certificate validation."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from backbone_conductor.auth import create_token_file
from backbone_conductor.dsh_agent import DSHRemoteMemberRunner
from backbone_conductor.service import Conductor


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def test_direct_https_requires_trusted_certificate_and_bearer_token(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "TLS Test")
    git(repo, "config", "user.email", "tls@example.invalid")
    Conductor(repo).initialize()
    credentials = tmp_path / "credentials.json"
    issued = create_token_file(credentials, repo, "owner", ["alice"])
    token = next(item["token"] for item in issued if item["name"] == "owner")
    member_token = next(item["token"] for item in issued if item["name"] == "alice")
    certificate = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except PermissionError:
            if os.environ.get("BACKBONE_REQUIRE_LIVE_HTTP") == "1":
                raise
            pytest.skip("This sandbox does not permit loopback listening sockets")
        port = listener.getsockname()[1]
    source_path = str(Path(__file__).resolve().parents[1] / "src")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "backbone_conductor",
            "--repo",
            str(repo),
            "serve",
            "--port",
            str(port),
            "--auth-file",
            str(credentials),
            "--mcp-http",
            "--tls-certfile",
            str(certificate),
            "--tls-keyfile",
            str(key),
        ],
        env={**os.environ, "PYTHONPATH": source_path},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"https://127.0.0.1:{port}"
    try:
        context = ssl.create_default_context(cafile=str(certificate))
        with httpx.Client(verify=context, trust_env=False, timeout=2) as client:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise AssertionError(f"TLS server exited: {server.stderr.read()}")
                try:
                    if client.get(f"{url}/health").status_code == 200:
                        break
                except httpx.RequestError:
                    time.sleep(0.1)
            else:
                raise AssertionError("TLS server did not become healthy")

            assert client.get(f"{url}/state").status_code == 401
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(f"{url}/state", headers=headers).status_code == 200
            response = client.post(
                f"{url}/intents",
                headers=headers,
                json={"id": "tls-intent", "problem": "Verify HTTPS", "proposed_outcome": "Pass"},
            )
            assert response.status_code == 201, response.text

        async def member_mcp() -> dict:
            async with httpx.AsyncClient(
                verify=context,
                trust_env=False,
                headers={"Authorization": f"Bearer {member_token}"},
            ) as http_client:
                async with streamable_http_client(f"{url}/mcp", http_client=http_client) as (
                    read,
                    write,
                    _session_id,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(
                            "create_intent",
                            {
                                "intent_data": {
                                    "id": "tls-mcp-intent",
                                    "problem": "Verify remote MCP with HTTPS",
                                    "proposed_outcome": "Persist through trusted TLS",
                                }
                            },
                        )
                        assert not result.isError
                        return json.loads(result.content[0].text)

        assert asyncio.run(member_mcp())["author"] == "alice"
        workspace = tmp_path / "member-workspace"
        workspace.mkdir()
        token_file = tmp_path / "alice.token"
        token_file.write_text(member_token + "\n", encoding="ascii")
        token_file.chmod(0o600)
        runner = DSHRemoteMemberRunner(
            workspace,
            tmp_path / "private-dsh-home",
            "alice",
            "placeholder",
            f"{url}/mcp",
            token_file,
            ca_file=certificate,
        )
        runner._preflight_mcp()
        assert runner._harness_env() == {"NODE_EXTRA_CA_CERTS": str(certificate)}
        if os.environ.get("BACKBONE_REQUIRE_DSH_MCP") == "1":
            from deepseek_harness import DeepSeekHarness

            patch = tmp_path / "trusted-remote.patch.yml"
            patch.write_text(json.dumps(runner.member_patch()), encoding="utf-8")
            patch.chmod(0o600)
            harness = DeepSeekHarness(
                dsh_home=str(runner.home),
                cwd=str(workspace),
                profile="sdk-minimal",
                patches=(str(patch),),
                provider="deepseek-official",
                model="placeholder",
                env=runner._harness_env(),
                initialize_timeout_seconds=30,
            )
            try:
                harness.start()
                assert harness._initialized
                assert harness.client._proc.poll() is None
            finally:
                harness.close()
        with httpx.Client(trust_env=False, timeout=2) as untrusted:
            with pytest.raises(httpx.RequestError):
                untrusted.get(f"{url}/health")
            with pytest.raises(httpx.RequestError):
                untrusted.get(f"http://127.0.0.1:{port}/health")
        history = git(repo, "log", "--format=%B", "--", ".backbone")
        assert "Backbone-HTTP-Principal: owner" in history
        assert "Backbone-HTTP-Principal: alice" in history
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate(timeout=5)
