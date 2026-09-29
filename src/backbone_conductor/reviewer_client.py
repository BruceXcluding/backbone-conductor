"""A small authenticated client for reviewers who do not hold the coordinator repo."""

from __future__ import annotations

import hashlib
import os
import re
import ssl
import stat
from pathlib import Path
from urllib.parse import urlsplit

import httpx

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _private_token(path: str) -> str:
    location = Path(path).expanduser().absolute()
    if location.is_symlink():
        raise ValueError("Reviewer token file must be a regular file, not a symlink")
    descriptor = os.open(
        location,
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Reviewer token file must be a single-link regular file")
        if metadata.st_uid != os.getuid() or metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("Reviewer token file must belong to this user and be mode 0600")
        raw = stream.read(1025)
    if len(raw) > 1024:
        raise ValueError("Reviewer token file is too large")
    try:
        token = raw.decode("ascii").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise ValueError("Reviewer token must be ASCII") from exc
    if not 32 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise ValueError("Reviewer token must be a single 32–512 character value")
    return token


def _server_url(value: str) -> str:
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Reviewer URL has an invalid port") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
        or port == 0
    ):
        raise ValueError("Reviewer URL must be an HTTP(S) server origin")
    if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote reviewer access requires HTTPS outside loopback")
    return value.rstrip("/")


def _identifier(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError("Reviewer command needs a valid Backbone identifier")
    return value


def _validated_audit_report(report: object, limit: int) -> dict:
    """Fail closed when a remote signature report violates its response contract."""
    error = ValueError("Reviewer server returned an invalid audit report")
    if not isinstance(report, dict):
        raise error
    counts = ("checked", "limit", "total_metadata_commits", "valid", "unsigned", "invalid")
    if any(type(report.get(key)) is not int or report[key] < 0 for key in counts):
        raise error
    if (
        report["limit"] != limit
        or report["checked"] > limit
        or report["total_metadata_commits"] < report["checked"]
        or report["checked"] != report["valid"] + report["unsigned"] + report["invalid"]
        or type(report.get("truncated")) is not bool
        or report["truncated"] != (report["total_metadata_commits"] > report["checked"])
        or type(report.get("all_inspected_signed_and_valid")) is not bool
        or report["all_inspected_signed_and_valid"]
        != (report["checked"] > 0 and report["valid"] == report["checked"])
    ):
        raise error
    commits = report.get("commits")
    if not isinstance(commits, list) or len(commits) != report["checked"]:
        raise error
    statuses = {"valid": 0, "unsigned": 0, "invalid": 0}
    for item in commits:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("commit"), str)
            or not _SHA.fullmatch(item["commit"])
            or not isinstance(item.get("signature"), str)
            or item.get("signature") not in statuses
        ):
            raise error
        statuses[item["signature"]] += 1
    if any(statuses[key] != report[key] for key in statuses):
        raise error
    return report


def _validated_full_patch(packet: object) -> dict:
    """Reject an incomplete or internally inconsistent remote review patch."""
    error = ValueError("Reviewer server returned an invalid full review patch")
    if not isinstance(packet, dict):
        raise error
    diff = packet.get("diff")
    if not isinstance(diff, dict):
        raise error
    patch = diff.get("patch")
    digest = diff.get("sha256")
    if not isinstance(patch, str) or not isinstance(digest, str):
        raise error
    try:
        patch_bytes = patch.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise error from exc
    if (
        diff.get("truncated") is not False
        or len(patch_bytes) > 1_000_000
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or hashlib.sha256(patch_bytes).hexdigest() != digest
    ):
        raise error
    return packet


def run_reviewer_command(args) -> dict | list:
    """Call the reviewer HTTP API once, binding write authors to its token identity."""
    origin = _server_url(args.url)
    token = _private_token(args.token_file)
    verify: ssl.SSLContext | bool = True
    if args.ca_file:
        certificate = Path(args.ca_file).expanduser().resolve(strict=True)
        if not certificate.is_file():
            raise ValueError("Reviewer CA file must be a regular file")
        verify = ssl.create_default_context(cafile=str(certificate))

    def request(
        client: httpx.Client,
        method: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
    ):
        try:
            response = client.request(method, path, json=data, params=params)
        except httpx.RequestError as exc:
            raise ValueError(f"Reviewer connection failed ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "Request failed")
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(
                f"Reviewer request failed (HTTP {response.status_code}): {str(detail)[:300]}"
            )
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Reviewer request failed (HTTP {response.status_code})")
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError("Reviewer server returned invalid JSON") from exc

    with httpx.Client(
        base_url=origin,
        headers={"Authorization": f"Bearer {token}"},
        verify=verify,
        trust_env=False,
        follow_redirects=False,
        timeout=20,
    ) as client:
        identity = request(client, "GET", "/whoami")
        if not isinstance(identity, dict) or identity.get("role") != "reviewer":
            raise ValueError("Reviewer token must identify a reviewer role")
        author = identity.get("name")
        if not isinstance(author, str) or not _ID.fullmatch(author):
            raise ValueError("Reviewer server returned an invalid principal")
        if args.action == "whoami":
            return identity
        if args.action == "state":
            return request(client, "GET", "/state")
        if args.action == "intents":
            return request(client, "GET", "/intents")
        if args.action == "decisions":
            return request(client, "GET", "/decisions")
        if args.action == "conflicts":
            return request(client, "GET", "/conflicts")
        if args.action == "tasks":
            return request(client, "GET", "/tasks")
        if args.action == "timeline":
            return request(
                client,
                "GET",
                "/timeline",
                params={
                    key: value
                    for key, value in {
                        "limit": args.limit,
                        "author": args.author,
                        "http_principal": args.http_principal,
                        "event_type": args.event_type,
                        "since": args.since,
                        "until": args.until,
                    }.items()
                    if value is not None
                },
            )
        if args.action == "audit-verify":
            report = request(client, "GET", "/audit/verify", params={"limit": args.limit})
            return _validated_audit_report(report, args.limit)
        if args.action == "inspect":
            packet = request(
                client,
                "GET",
                f"/tasks/{_identifier(args.task_id)}/inspection",
                params={"full_patch": True} if args.full else None,
            )
            return _validated_full_patch(packet) if args.full else packet
        if args.action == "review-intent":
            return request(
                client,
                "POST",
                f"/intents/{_identifier(args.intent_id)}/review",
                {
                    "author": author,
                    "outcome": args.outcome,
                    "rationale": args.rationale,
                    "expected_version": args.version,
                },
            )
        if args.action == "revert-decision":
            return request(
                client,
                "POST",
                f"/decisions/{_identifier(args.decision_id)}/revert",
                {
                    "author": author,
                    "rationale": args.rationale,
                    "expected_version": args.version,
                },
            )
        if args.action == "resolve-conflict":
            return request(
                client,
                "POST",
                f"/conflicts/{_identifier(args.conflict_id)}/resolve",
                {
                    "author": author,
                    "action": args.resolution_action,
                    "rationale": args.rationale,
                    "expected_version": args.version,
                },
            )
        if args.action == "approve":
            return request(
                client,
                "POST",
                f"/tasks/{_identifier(args.task_id)}/merge",
                {
                    "author": author,
                    "rationale": args.rationale,
                    "expected_version": args.version,
                    "expected_target_sha": args.target_sha,
                },
            )
        raise ValueError(f"Unknown reviewer command: {args.action}")
