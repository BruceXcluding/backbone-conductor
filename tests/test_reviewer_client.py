"""Keep reviewer credentials local and require TLS away from loopback."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from backbone_conductor.cli import _format_inspection, main
from backbone_conductor.reviewer_client import (
    _private_token,
    _validated_audit_report,
    _validated_full_patch,
)


def test_reviewer_cli_requires_https_for_non_loopback(tmp_path: Path, capsys) -> None:
    token = tmp_path / "reviewer.token"
    token.write_text("r" * 48 + "\n", encoding="ascii")
    token.chmod(0o600)
    assert (
        main(
            [
                "reviewer",
                "--url",
                "http://coordinator.example.org",
                "--token-file",
                str(token),
                "whoami",
            ]
        )
        == 1
    )
    assert "requires HTTPS" in json.loads(capsys.readouterr().err)["error"]


def test_reviewer_token_file_rejects_shared_or_linked_credentials(tmp_path: Path) -> None:
    token = tmp_path / "reviewer.token"
    token.write_text("r" * 48 + "\n", encoding="ascii")
    token.chmod(0o600)
    assert _private_token(str(token)) == "r" * 48

    token.chmod(0o644)
    with pytest.raises(ValueError, match="mode 0600"):
        _private_token(str(token))
    token.chmod(0o600)

    symlink = tmp_path / "linked.token"
    symlink.symlink_to(token)
    with pytest.raises(ValueError, match="symlink"):
        _private_token(str(symlink))

    hardlink = tmp_path / "hardlinked.token"
    os.link(token, hardlink)
    with pytest.raises(ValueError, match="single-link"):
        _private_token(str(token))


def test_remote_audit_report_rejects_inconsistent_signature_counts() -> None:
    report = {
        "checked": 1,
        "limit": 1,
        "total_metadata_commits": 2,
        "truncated": True,
        "valid": 0,
        "unsigned": 1,
        "invalid": 0,
        "all_inspected_signed_and_valid": False,
        "commits": [{"commit": "a" * 40, "signature": "unsigned"}],
    }
    assert _validated_audit_report(report, 1) == report
    for bad in (
        {**report, "all_inspected_signed_and_valid": True},
        {**report, "valid": 1},
        {**report, "commits": [{"commit": "a" * 40, "signature": {}}]},
    ):
        with pytest.raises(ValueError, match="invalid audit report"):
            _validated_audit_report(bad, 1)


def test_remote_full_patch_rejects_truncation_or_hash_mismatch() -> None:
    patch = "diff --git a/a b/a\n+é\n"
    packet = {
        "git": {
            "base_sha": "a" * 40,
            "target_sha": "b" * 40,
            "integrated_into_target": False,
        },
        "diff": {
            "patch": patch,
            "truncated": False,
            "sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "changed_paths": ["a"],
        },
    }
    assert _validated_full_patch(packet) == packet
    for bad in (
        {"diff": {**packet["diff"], "patch": patch[:-1]}},
        {"diff": {**packet["diff"], "truncated": True}},
        {"diff": {**packet["diff"], "sha256": "0" * 64}},
        {"diff": {**packet["diff"], "patch": "x" * 1_000_001}},
    ):
        with pytest.raises(ValueError, match="invalid full review patch"):
            _validated_full_patch(bad)

    integrated = {
        **packet,
        "git": {**packet["git"], "integrated_into_target": True},
        "target_diff": {
            **packet["diff"],
            "base_sha": "a" * 40,
            "target_sha": "b" * 40,
        },
    }
    assert _validated_full_patch(integrated) == integrated
    for bad in (
        {**integrated, "target_diff": None},
        {
            **integrated,
            "target_diff": {**integrated["target_diff"], "patch": patch[:-1]},
        },
        {
            **integrated,
            "target_diff": {**integrated["target_diff"], "target_sha": "c" * 40},
        },
        {**packet, "target_diff": integrated["target_diff"]},
    ):
        with pytest.raises(ValueError, match="invalid full review patch"):
            _validated_full_patch(bad)


def test_text_inspection_shows_patch_lines_and_marks_unverified_preview() -> None:
    patch = "diff --git a/a b/a\n+one\n+two\n"
    digest = hashlib.sha256(patch.encode()).hexdigest()
    packet = {
        "version": "v1",
        "task": {"id": "task-1"},
        "git": {
            "base_sha": "a" * 40,
            "artifact_sha": "b" * 40,
            "target_sha": "c" * 40,
            "integrated_into_target": False,
        },
        "diff": {
            "patch": patch,
            "truncated": False,
            "sha256": digest,
            "changed_paths": ["a"],
        },
        "target_diff": None,
    }
    rendered = _format_inspection(packet)
    assert "+one\n+two" in rendered
    assert f"Full patch SHA-256: {digest}" in rendered
    assert "Integrated target diff: pending Git merge." in rendered
    assert "TRUNCATED PREVIEW" not in rendered

    preview = {**packet, "diff": {**packet["diff"], "patch": patch[:10], "truncated": True}}
    rendered = _format_inspection(preview)
    assert "TRUNCATED PREVIEW" in rendered
    assert "Review the complete patch with --full" in rendered

    integrated = {
        **packet,
        "git": {**packet["git"], "integrated_into_target": True},
        "target_diff": {
            **packet["diff"],
            "base_sha": "a" * 40,
            "target_sha": "c" * 40,
        },
    }
    assert "Integrated target paths versus base" in _format_inspection(integrated)
    with pytest.raises(ValueError, match="SHA-256"):
        _format_inspection({**packet, "diff": {**packet["diff"], "patch": patch[:-1]}})
    with pytest.raises(ValueError, match="not bound"):
        _format_inspection(
            {
                **integrated,
                "target_diff": {**integrated["target_diff"], "changed_paths": ["other"]},
            }
        )


def test_text_inspection_escapes_terminal_controls_in_patch() -> None:
    patch = "diff --git a/a b/a\n+\x1b[31m\u202eevil\u2028\n"
    packet = {
        "version": "v1",
        "task": {"id": "task-1"},
        "git": {
            "base_sha": "a" * 40,
            "artifact_sha": "b" * 40,
            "target_sha": "c" * 40,
            "integrated_into_target": False,
        },
        "diff": {
            "patch": patch,
            "truncated": False,
            "sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "changed_paths": ["a"],
        },
        "target_diff": None,
    }
    rendered = _format_inspection(packet)
    assert "\\x1b[31m\\u202eevil\\u2028" in rendered
    assert "\x1b" not in rendered
    assert "\u202e" not in rendered
