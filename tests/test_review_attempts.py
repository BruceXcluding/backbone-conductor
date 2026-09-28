"""Review failure telemetry must remain outside Git in an owner-only file."""

from __future__ import annotations

from pathlib import Path

import pytest

from backbone_conductor.cli import build_parser
from backbone_conductor.review_attempts import ReviewAttemptLog


def test_review_attempt_log_rejects_repo_and_unsafe_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="outside the repository"):
        ReviewAttemptLog(repo / "attempts.jsonl", (repo,))
    with pytest.raises(ValueError, match="private"):
        ReviewAttemptLog(public / "attempts.jsonl", (repo,))

    target = private / "target.jsonl"
    target.write_text("old\n")
    target.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        ReviewAttemptLog(target, (repo,))
    link = private / "link.jsonl"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        ReviewAttemptLog(link, (repo,))
    inside = repo / "inside.jsonl"
    inside.write_text("untouched\n")
    inside.chmod(0o600)
    hardlink = private / "hardlink.jsonl"
    hardlink.hardlink_to(inside)
    with pytest.raises(ValueError, match="owner-only"):
        ReviewAttemptLog(hardlink, (repo,))
    assert inside.read_text() == "untouched\n"
    assert target.read_text() == "old\n"


def test_review_cli_accepts_private_attempt_log_option() -> None:
    args = build_parser().parse_args(
        [
            "review",
            "task-1",
            "--dsh-home",
            "/private/dsh",
            "--model",
            "model-1",
            "--attempt-log",
            "/private/review-attempts.jsonl",
        ]
    )
    assert args.attempt_log == "/private/review-attempts.jsonl"
