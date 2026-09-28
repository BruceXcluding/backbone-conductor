"""Verify that direct TLS serves authenticated HTTP with certificate validation."""

from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from backbone_conductor.auth import create_token_file
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
    token = create_token_file(credentials, repo, "owner", [])[0]["token"]
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
        with httpx.Client(trust_env=False, timeout=2) as untrusted:
            with pytest.raises(httpx.RequestError):
                untrusted.get(f"{url}/health")
            with pytest.raises(httpx.RequestError):
                untrusted.get(f"http://127.0.0.1:{port}/health")
        assert "Backbone-HTTP-Principal: owner" in git(repo, "log", "-1", "--format=%B")
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate(timeout=5)
