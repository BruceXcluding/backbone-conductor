"""Opt-in bearer authentication for the HTTP transport.

Credentials live outside the Git ledger. The file contains only SHA-256 digests
of randomly generated, high-entropy bearer tokens, never plaintext tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,199}\Z")


@dataclass(frozen=True)
class Principal:
    name: str
    role: str


class TokenAuth:
    """Verify tokens against a private, strictly validated credential file."""

    def __init__(self, path: str | Path, repo: str | Path) -> None:
        location = Path(path).expanduser().resolve(strict=True)
        repository = Path(repo).expanduser().resolve()
        if location.is_relative_to(repository):
            raise ValueError("HTTP credential file must be outside the repository")
        if not location.is_file():
            raise ValueError("HTTP credential file must be a regular file")
        mode = location.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("HTTP credential file must be accessible only to its owner (0600)")
        try:
            config = json.loads(location.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid HTTP credential file: {exc}") from exc
        if not isinstance(config, dict) or set(config) != {"tokens"}:
            raise ValueError("HTTP credential file must contain only a tokens array")
        entries = config["tokens"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("HTTP credential file needs at least one token")
        self._tokens: list[tuple[str, Principal]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"name", "role", "sha256"}:
                raise ValueError("Each token needs name, role and sha256 only")
            name, role, digest = entry["name"], entry["role"], entry["sha256"]
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise ValueError("Invalid HTTP token principal name")
            if not isinstance(role, str) or role not in {"admin", "member"}:
                raise ValueError("HTTP token role must be admin or member")
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or digest in seen:
                raise ValueError("HTTP token sha256 must be unique lowercase hex")
            seen.add(digest)
            self._tokens.append((digest, Principal(name, role)))
        if not any(principal.role == "admin" for _, principal in self._tokens):
            raise ValueError("HTTP credential file needs an admin token")

    def authenticate(self, authorization: str | None) -> Principal | None:
        if not authorization or not authorization.startswith("Bearer "):
            return None
        token = authorization[7:]
        if len(token) < 32 or len(token) > 512 or any(character.isspace() for character in token):
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        matched = None
        for expected, principal in self._tokens:
            if secrets.compare_digest(expected, digest):
                matched = principal
        return matched


def create_token_file(
    path: str | Path, repo: str | Path, admin: str, members: list[str]
) -> list[dict[str, str]]:
    """Create a private digest file and return one-time plaintext credentials."""
    repository = Path(repo).expanduser().resolve()
    location = Path(path).expanduser().resolve()
    principals = [(admin, "admin"), *((member, "member") for member in members)]
    names = [name for name, _ in principals]
    if any(not _NAME.fullmatch(name) for name in names) or len(set(names)) != len(names):
        raise ValueError("Token principal names must be unique and use safe characters")
    if location.is_relative_to(repository):
        raise ValueError("HTTP credential file must be outside the repository")
    issued = [
        {"name": name, "role": role, "token": secrets.token_urlsafe(48)}
        for name, role in principals
    ]
    digests = [
        {
            "name": item["name"],
            "role": item["role"],
            "sha256": hashlib.sha256(item["token"].encode("utf-8")).hexdigest(),
        }
        for item in issued
    ]
    descriptor = os.open(location, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"tokens": digests}, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        TokenAuth(location, repository)
    except BaseException:
        location.unlink(missing_ok=True)
        raise
    return issued
