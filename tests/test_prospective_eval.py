"""Prospective evaluation must keep predictions and independent labels separate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "evaluate_prospective.py"
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_prospective import freeze, score  # noqa: E402


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
