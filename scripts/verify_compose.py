"""Exercise both Compose modes against real Docker, Git, and HTTP on a host."""

from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from backbone_conductor.auth import create_token_file, rotate_token_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


def command(*args: str, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}\n{error.stdout}\n{error.stderr}"
        ) from error
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return command("git", "-C", str(repo), *args)


def compose(
    project: str, env: dict[str, str], *args: str, separate: bool = False, tls: bool = False
) -> str:
    files = ["-f", str(PROJECT_ROOT / "compose.yaml")]
    if tls:
        files += ["-f", str(PROJECT_ROOT / "compose.tls.yaml")]
        if separate:
            files += ["-f", str(PROJECT_ROOT / "compose.ledger-tls.yaml")]
    elif separate:
        files += ["-f", str(PROJECT_ROOT / "compose.ledger.yaml")]
    return command("docker", "compose", "-p", project, *files, *args, env=env)


def port_available() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(
    port: int,
    path: str,
    token: str | None = None,
    data: dict | None = None,
    certificate: Path | None = None,
) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    scheme = "https" if certificate else "http"
    target = Request(f"{scheme}://127.0.0.1:{port}{path}", data=body, headers=headers)
    opener = HTTP
    if certificate:
        context = ssl.create_default_context(cafile=str(certificate))
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
    try:
        with opener.open(target, timeout=2) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


def wait_healthy(port: int, certificate: Path | None = None) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if request(port, "/health", certificate=certificate)[0] == 200:
                return
        except (OSError, HTTPException):
            pass
        time.sleep(0.2)
    raise AssertionError(f"Compose service on port {port} did not become healthy")


def setup_repo(repo: Path) -> None:
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Compose Verification")
    git(repo, "config", "user.email", "compose@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "commit", "--allow-empty", "-m", "Seed code branch")


def verify_inline(project: str, repo: Path, auth_dir: Path, old_token: str, port: int) -> str:
    env = {**os.environ, "BACKBONE_REPO": str(repo), "BACKBONE_AUTH_DIR": str(auth_dir)}
    env["BACKBONE_PORT"] = str(port)
    env["BACKBONE_UID"] = str(os.getuid())
    env["BACKBONE_GID"] = str(os.getgid())
    compose(project, env, "build")
    try:
        compose(project, env, "run", "--rm", "conductor", "--repo", "/workspace", "init")
        compose(project, env, "up", "-d")
        wait_healthy(port)
        assert request(port, "/state")[0] == 401
        assert request(port, "/state", old_token)[0] == 200
        status, intent = request(
            port,
            "/intents",
            old_token,
            {"id": "inline-intent", "problem": "Verify inline Compose", "proposed_outcome": "Pass"},
        )
        assert status == 201 and intent["id"] == "inline-intent", (status, intent)
        assert git(repo, "status", "--porcelain") == ""
        assert "Backbone-HTTP-Principal: owner" in git(repo, "log", "-1", "--format=%B")
        new_token = rotate_token_file(auth_dir / "backbone-http-tokens.json", repo, "owner", [])[0][
            "token"
        ]
        assert request(port, "/state", old_token)[0] == 401
        assert request(port, "/state", new_token)[0] == 200
        return new_token
    finally:
        compose(project, env, "down")


def verify_separate(project: str, repo: Path, auth_dir: Path, token: str, port: int) -> None:
    env = {**os.environ, "BACKBONE_REPO": str(repo), "BACKBONE_AUTH_DIR": str(auth_dir)}
    env["BACKBONE_PORT"] = str(port)
    env["BACKBONE_UID"] = str(os.getuid())
    env["BACKBONE_GID"] = str(os.getgid())
    initial_head = git(repo, "rev-parse", "HEAD")
    try:
        compose(
            project,
            env,
            "run",
            "--rm",
            "conductor",
            "--repo",
            "/workspace",
            "ledger",
            "create",
            separate=True,
        )
        old_ledger_head = git(repo, "rev-parse", "backbone")
        compose(project, env, "up", "-d", separate=True)
        wait_healthy(port)
        status, intent = request(
            port,
            "/intents",
            token,
            {
                "id": "separate-intent",
                "problem": "Verify separate Compose",
                "proposed_outcome": "Pass",
            },
        )
        assert status == 201 and intent["id"] == "separate-intent", (status, intent)
        assert git(repo, "rev-parse", "HEAD") == initial_head
        assert git(repo, "rev-parse", "backbone") != old_ledger_head
        assert git(repo, "status", "--porcelain") == ""
        assert "Backbone-HTTP-Principal: owner" in git(repo, "log", "-1", "backbone", "--format=%B")
        compose(project, env, "restart", separate=True)
        wait_healthy(port)
        status, state = request(port, "/state", token)
        assert status == 200 and "separate-intent" in state["intents"], (status, state)
    finally:
        compose(project, env, "down", separate=True)


def create_test_certificate(directory: Path) -> Path:
    directory.mkdir(mode=0o700)
    certificate = directory / "server.crt"
    key = directory / "server.key"
    command(
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
    )
    key.chmod(0o600)
    return certificate


def verify_tls(
    project: str,
    repo: Path,
    auth_dir: Path,
    tls_dir: Path,
    token: str,
    *,
    separate: bool,
) -> None:
    port = port_available()
    base_port = port_available()
    while base_port == port:
        base_port = port_available()
    env = {
        **os.environ,
        "BACKBONE_REPO": str(repo),
        "BACKBONE_AUTH_DIR": str(auth_dir),
        "BACKBONE_TLS_DIR": str(tls_dir),
        "BACKBONE_PORT": str(base_port),
        "BACKBONE_TLS_PORT": str(port),
        "BACKBONE_UID": str(os.getuid()),
        "BACKBONE_GID": str(os.getgid()),
    }
    certificate = tls_dir / "server.crt"
    branch = "backbone" if separate else "HEAD"
    code_head = git(repo, "rev-parse", "HEAD")
    ledger_head = git(repo, "rev-parse", branch)
    try:
        compose(project, env, "config", "--quiet", separate=separate, tls=True)
        compose(project, env, "up", "-d", separate=separate, tls=True)
        wait_healthy(port, certificate)
        assert request(port, "/state", certificate=certificate)[0] == 401
        assert request(port, "/state", token, certificate=certificate)[0] == 200
        intent_id = "tls-separate-intent" if separate else "tls-inline-intent"
        status, intent = request(
            port,
            "/intents",
            token,
            {"id": intent_id, "problem": "Verify Compose HTTPS", "proposed_outcome": "Pass"},
            certificate,
        )
        assert status == 201 and intent["id"] == intent_id, (status, intent)
        assert git(repo, "rev-parse", branch) != ledger_head
        assert "Backbone-HTTP-Principal: owner" in git(repo, "log", "-1", branch, "--format=%B")
        assert git(repo, "status", "--porcelain") == ""
        if separate:
            assert git(repo, "rev-parse", "HEAD") == code_head
        try:
            with HTTP.open(f"https://127.0.0.1:{port}/health", timeout=2):
                pass
        except URLError:
            pass
        else:
            raise AssertionError("Untrusted TLS certificate was accepted")
        for plain_port in (port, base_port):
            try:
                with HTTP.open(f"http://127.0.0.1:{plain_port}/health", timeout=2) as response:
                    assert response.status != 200
            except (OSError, HTTPException):
                pass
        compose(project, env, "restart", separate=separate, tls=True)
        wait_healthy(port, certificate)
        status, state = request(port, "/state", token, certificate=certificate)
        assert status == 200 and intent_id in state["intents"], (status, state)
    except BaseException:
        try:
            print(compose(project, env, "logs", "--no-color", separate=separate, tls=True))
        except Exception:
            pass
        raise
    finally:
        compose(project, env, "down", separate=separate, tls=True)


def main() -> None:
    temporary_root = "/private/tmp" if sys.platform == "darwin" else "/tmp"
    with tempfile.TemporaryDirectory(prefix="backbone-compose-", dir=temporary_root) as temporary:
        root = Path(temporary)
        inline_repo = root / "inline"
        separate_repo = root / "separate"
        setup_repo(inline_repo)
        setup_repo(separate_repo)
        auth_dir = root / "auth"
        auth_dir.mkdir(mode=0o700)
        old_token = create_token_file(
            auth_dir / "backbone-http-tokens.json", inline_repo, "owner", []
        )[0]["token"]
        project = f"backbone-compose-{os.getpid()}"
        new_token = verify_inline(project, inline_repo, auth_dir, old_token, port_available())
        verify_separate(project, separate_repo, auth_dir, new_token, port_available())
        tls_dir = root / "tls"
        create_test_certificate(tls_dir)
        verify_tls(project, inline_repo, auth_dir, tls_dir, new_token, separate=False)
        verify_tls(project, separate_repo, auth_dir, tls_dir, new_token, separate=True)
    print("Compose HTTP and HTTPS inline and separate-ledger verification passed")


if __name__ == "__main__":
    main()
