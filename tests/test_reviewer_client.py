"""Keep reviewer credentials local and require TLS away from loopback."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backbone_conductor.cli import main
from backbone_conductor.reviewer_client import _private_token


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
