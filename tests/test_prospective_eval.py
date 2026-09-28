"""Prospective evaluation must keep predictions and independent labels separate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backbone_conductor.ledger import create_ledger
from backbone_conductor.service import Conductor

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "evaluate_prospective.py"
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prospective import capture, freeze, score  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _capture_repo(tmp_path: Path, *, separate_ledger: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Study")
    _git(repo, "config", "user.email", "study@example.invalid")
    (repo / "app.py").write_text("value = 1\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "Initial code")
    if separate_ledger:
        create_ledger(repo)
        conductor = Conductor(repo, ledger_branch="backbone")
    else:
        conductor = Conductor(repo)
        conductor.initialize()
    for name, path in (
        ("alice", "src/shared.py"),
        ("bob", "src/shared.py"),
        ("carol", "src/other.py"),
    ):
        conductor.create_intent(
            {
                "id": f"intent-{name}",
                "author": name,
                "problem": f"Plan {name}'s work",
                "proposed_outcome": "Complete the planned change",
                "affected_paths": [path],
            }
        )
    return repo


def test_capture_freezes_all_unassigned_pairs_from_real_git_baseline(tmp_path: Path):
    repo = _capture_repo(tmp_path)
    dataset = tmp_path / "cases.json"
    predictions = tmp_path / "predictions.json"
    baseline = _git(repo, "rev-parse", "HEAD")
    command = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "capture",
            "--repo",
            str(repo),
            "--project",
            "example/project",
            "--sampling",
            "All unassigned pairs at this snapshot",
            "--dataset",
            str(dataset),
            "--predictions",
            str(predictions),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert command.returncode == 0, command.stderr
    result = json.loads(command.stdout)
    assert result["case_count"] == 3
    assert result["base_sha"] == baseline
    assert result["backbone_version"] == Conductor(repo).state()["version"]
    data = json.loads(dataset.read_text())
    assert len(data["cases"]) == 3
    assert {case["base_sha"] for case in data["cases"]} == {baseline}
    assert all(len({item["author"] for item in case["intents"]}) == 2 for case in data["cases"])
    frozen = json.loads(predictions.read_text())
    assert sum(bool(case["findings"]) for case in frozen["cases"]) == 1
    assert dataset.stat().st_mode & 0o777 == 0o600
    assert predictions.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        capture(repo, "example/project", "Same snapshot", dataset, predictions)
    assert _git(repo, "status", "--porcelain") == ""


def test_capture_rejects_dirty_or_public_checkout_outputs(tmp_path: Path):
    repo = _capture_repo(tmp_path)
    dataset = tmp_path / "cases.json"
    predictions = tmp_path / "predictions.json"
    with pytest.raises(ValueError, match="outside the public code repository"):
        capture(repo, "example/project", "All pairs", repo / "cases.json", predictions)
    (repo / "untracked.txt").write_text("unfinished work\n")
    with pytest.raises(ValueError, match="clean"):
        capture(repo, "example/project", "All pairs", dataset, predictions)
    assert not dataset.exists() and not predictions.exists()


def test_capture_excludes_reopened_intents_with_task_history(tmp_path: Path):
    repo = _capture_repo(tmp_path)
    conductor = Conductor(repo)
    conductor.transition_intent("intent-carol", "accepted")
    task = conductor.dispatch_task("intent-carol", "carol")
    conductor.cancel_task(task["id"], "coordinator", "Replan before implementation")
    assert conductor.state()["intents"]["intent-carol"]["status"] == "accepted"
    dataset = tmp_path / "cases.json"
    capture(repo, "example/project", "All eligible pairs", dataset, tmp_path / "predictions.json")
    assert [case["id"] for case in json.loads(dataset.read_text())["cases"]] == [
        "pair-intent-alice-intent-bob"
    ]


def test_capture_separate_ledger_records_code_baseline(tmp_path: Path):
    repo = _capture_repo(tmp_path, separate_ledger=True)
    code_sha = _git(repo, "rev-parse", "HEAD")
    result = capture(
        repo,
        "example/project",
        "All unassigned pairs in the separate ledger",
        tmp_path / "cases.json",
        tmp_path / "predictions.json",
        ledger_branch="backbone",
    )
    assert result["base_sha"] == code_sha
    assert result["backbone_version"] != code_sha
    assert _git(repo, "status", "--porcelain") == ""


def _case(identifier: str, left_path: str, right_path: str) -> dict:
    return {
        "id": identifier,
        "project": "example/project",
        "base_sha": "a" * 40,
        "captured_at": "2026-09-29T10:00:00Z",
        "intents": [
            {
                "id": f"{identifier}-alice",
                "author": "alice",
                "problem": "Change the first component",
                "proposed_outcome": "Complete planned work",
                "affected_paths": [left_path],
                "created_at": "2026-09-29T09:00:00Z",
            },
            {
                "id": f"{identifier}-bob",
                "author": "bob",
                "problem": "Change the second component",
                "proposed_outcome": "Complete planned work",
                "affected_paths": [right_path],
                "created_at": "2026-09-29T09:30:00Z",
            },
        ],
    }


def _files(tmp_path: Path, cases: list[dict]) -> tuple[Path, Path]:
    dataset = tmp_path / "cases.json"
    predictions = tmp_path / "predictions.json"
    dataset.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sampling": "Consecutive eligible task pairs before work starts",
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    freeze(dataset, predictions)
    return dataset, predictions


def _reviews(
    path: Path, dataset: Path, predictions: Path, reviewer: str, cases: list[dict]
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                "predictions_sha256": hashlib.sha256(predictions.read_bytes()).hexdigest(),
                "reviewer": reviewer,
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )


def _review(identifier: str, conflict: bool) -> dict:
    return {"id": identifier, "conflict": conflict, "rationale": "Reviewed both planned changes"}


def test_prospective_score_exposes_false_positives_and_missed_semantic_conflicts(tmp_path):
    dataset, predictions = _files(
        tmp_path,
        [
            _case("true-positive", "src/shared.py", "src/shared.py"),
            _case("false-positive", "src/shared.py", "src/shared.py"),
            _case("false-negative", "src/one.py", "src/two.py"),
            _case("true-negative", "src/one.py", "src/two.py"),
        ],
    )
    first = tmp_path / "carol.json"
    second = tmp_path / "dave.json"
    cases = [
        _review(identifier, conflict)
        for identifier, conflict in (
            ("true-positive", True),
            ("false-positive", False),
            ("false-negative", True),
            ("true-negative", False),
        )
    ]
    _reviews(first, dataset, predictions, "carol", cases)
    _reviews(second, dataset, predictions, "dave", cases)
    result = score(dataset, predictions, first, second)
    assert result["status"] == "complete_sample"
    assert result["counts"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert result["precision"] == result["recall"] == result["f1"] == 0.5
    assert "cannot prove" in result["limitation"]


def test_missing_and_disputed_labels_do_not_become_negative_cases(tmp_path):
    dataset, predictions = _files(
        tmp_path,
        [
            _case("disputed", "src/shared.py", "src/shared.py"),
            _case("unlabeled", "src/one.py", "src/two.py"),
        ],
    )
    first = tmp_path / "carol.json"
    second = tmp_path / "dave.json"
    adjudication = tmp_path / "erin.json"
    _reviews(first, dataset, predictions, "carol", [_review("disputed", True)])
    _reviews(second, dataset, predictions, "dave", [_review("disputed", False)])
    result = score(dataset, predictions, first, second)
    assert result["status"] == "incomplete"
    assert result["resolved_count"] == 0
    assert result["recall"] is None
    assert [row["status"] for row in result["cases"]] == ["disputed", "unlabeled"]

    _reviews(adjudication, dataset, predictions, "erin", [_review("disputed", True)])
    result = score(dataset, predictions, first, second, adjudication)
    assert result["resolved_count"] == 1
    assert result["counts"]["tp"] == 1
    assert result["status"] == "incomplete"


def test_freeze_is_exclusive_and_labels_bind_exact_inputs(tmp_path):
    dataset, predictions = _files(tmp_path, [_case("pair", "src/shared.py", "src/shared.py")])
    with pytest.raises(FileExistsError):
        freeze(dataset, predictions)
    first = tmp_path / "carol.json"
    second = tmp_path / "dave.json"
    _reviews(first, dataset, predictions, "carol", [_review("pair", True)])
    _reviews(second, dataset, predictions, "dave", [_review("pair", True)])
    contents = json.loads(dataset.read_text())
    contents["sampling"] = "Changed after predictions were frozen"
    dataset.write_text(json.dumps(contents))
    with pytest.raises(ValueError, match="frozen dataset"):
        score(dataset, predictions, first, second)


def test_self_review_and_prediction_tampering_are_rejected(tmp_path):
    dataset, predictions = _files(tmp_path, [_case("pair", "src/shared.py", "src/shared.py")])
    first = tmp_path / "alice.json"
    second = tmp_path / "dave.json"
    _reviews(first, dataset, predictions, "alice", [_review("pair", True)])
    _reviews(second, dataset, predictions, "dave", [_review("pair", True)])
    with pytest.raises(ValueError, match="reviewer must differ"):
        score(dataset, predictions, first, second)

    _reviews(first, dataset, predictions, "carol", [_review("pair", True)])
    frozen = json.loads(predictions.read_text())
    frozen["cases"][0]["findings"] = []
    predictions.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match="review does not match"):
        score(dataset, predictions, first, second)


def test_cli_reports_incomplete_sample_without_claiming_target(tmp_path):
    dataset, predictions = _files(tmp_path, [_case("pair", "src/one.py", "src/two.py")])
    first = tmp_path / "carol.json"
    second = tmp_path / "dave.json"
    _reviews(first, dataset, predictions, "carol", [])
    _reviews(second, dataset, predictions, "dave", [])
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "score",
            "--dataset",
            str(dataset),
            "--predictions",
            str(predictions),
            "--review",
            str(first),
            "--review",
            str(second),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "incomplete"
    assert report["recall"] is None
    assert report["precision"] is None


@pytest.mark.parametrize("mutation", ["future_intent", "same_author", "post_work_status"])
def test_freeze_rejects_cases_that_are_not_two_prework_intents(tmp_path, mutation):
    case = _case("pair", "src/one.py", "src/two.py")
    if mutation == "future_intent":
        case["intents"][1]["created_at"] = "2026-09-29T11:00:00Z"
    elif mutation == "same_author":
        case["intents"][1]["author"] = "alice"
    else:
        case["intents"][1]["status"] = "in_progress"
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps({"schema_version": 1, "sampling": "Consecutive task pairs", "cases": [case]})
    )
    with pytest.raises(ValueError):
        freeze(dataset, tmp_path / "predictions.json")
