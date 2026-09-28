#!/usr/bin/env python3
"""Freeze pre-work conflict warnings, then score separately reviewed outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbone_conductor.conflicts import detect_conflicts  # noqa: E402
from backbone_conductor.models import BackboneState, Intent, IntentStatus  # noqa: E402
from backbone_conductor.service import Conductor  # noqa: E402

SHA = re.compile(r"[0-9a-f]{40}\Z")
LIMITATION = (
    "Scores cover only independently reviewed, resolved cases in this submitted sample. "
    "Only pre-work intent-pair warnings are scored; decision and task rules are excluded. "
    "Names and timestamps are self-reported; this tool cannot prove prospective collection, "
    "reviewer independence, representative sampling, or real-world detection >=80%."
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO 8601 timestamp with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 timestamp with timezone") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return result


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _dataset(path: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], list[Intent]]]]:
    data = _read(path)
    if set(data) != {"schema_version", "sampling", "cases"} or data["schema_version"] != 1:
        raise ValueError("dataset requires schema_version 1, sampling, and cases")
    _nonempty(data["sampling"], "sampling")
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise ValueError("dataset requires at least one case")
    parsed: list[tuple[dict[str, Any], list[Intent]]] = []
    seen: set[str] = set()
    for case in data["cases"]:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "project",
            "base_sha",
            "captured_at",
            "intents",
        }:
            raise ValueError("each case requires id, project, base_sha, captured_at, intents")
        case_id = _nonempty(case["id"], "case id")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        _nonempty(case["project"], f"{case_id} project")
        if not isinstance(case["base_sha"], str) or not SHA.fullmatch(case["base_sha"]):
            raise ValueError(f"{case_id} base_sha must be a full Git SHA")
        captured_at = _timestamp(case["captured_at"], f"{case_id} captured_at")
        if not isinstance(case["intents"], list) or len(case["intents"]) != 2:
            raise ValueError(f"{case_id} requires exactly two pre-work intents")
        for raw in case["intents"]:
            if not isinstance(raw, dict) or "id" not in raw or "created_at" not in raw:
                raise ValueError(f"{case_id} intents require explicit id and created_at")
        intents = [Intent.model_validate(item) for item in case["intents"]]
        if len({item.id for item in intents}) != 2 or len({item.author for item in intents}) != 2:
            raise ValueError(f"{case_id} intents require distinct IDs and authors")
        if any(item.status not in {IntentStatus.DRAFT, IntentStatus.ACCEPTED} for item in intents):
            raise ValueError(f"{case_id} intents must be draft or accepted at capture")
        if any(item.created_at > captured_at for item in intents):
            raise ValueError(f"{case_id} intent timestamp is after capture")
        parsed.append((case, intents))
    return data, parsed


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    """Publish a complete private JSON file without replacing an existing artifact."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".backbone-study-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def capture(
    repo: Path,
    project: str,
    sampling: str,
    dataset: Path,
    predictions: Path,
    ledger_branch: str | None = None,
) -> dict[str, Any]:
    """Capture all currently unassigned pre-work intent pairs and freeze warnings."""
    conductor = Conductor(repo, ledger_branch=ledger_branch)
    root = conductor.code_store.root
    if not dataset.is_absolute() or not predictions.is_absolute():
        raise ValueError("dataset and predictions must use absolute private paths")
    if dataset.resolve() == predictions.resolve():
        raise ValueError("dataset and predictions must be different files")
    if any(path.resolve().is_relative_to(root) for path in (dataset, predictions)):
        raise ValueError("study files must be outside the public code repository")
    _nonempty(project, "project")
    _nonempty(sampling, "sampling")
    if dataset.exists() or predictions.exists():
        raise FileExistsError("study outputs already exist; capture never overwrites evidence")
    if conductor.code_store._git("status", "--porcelain", "--untracked-files=all").stdout:
        raise ValueError("code worktree must be clean before capturing a baseline")
    base_sha = conductor.code_store._git("rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    state = conductor.store.read()
    assigned = {task.intent_id for task in state.tasks.values()}
    eligible = sorted(
        (
            intent
            for intent in state.intents.values()
            if intent.status in {IntentStatus.DRAFT, IntentStatus.ACCEPTED}
            and intent.id not in assigned
        ),
        key=lambda intent: intent.id,
    )
    captured_at = datetime.now(UTC)
    cases = [
        {
            "id": f"pair-{left.id}-{right.id}",
            "project": project,
            "base_sha": base_sha,
            "captured_at": captured_at.isoformat(),
            "intents": [left.model_dump(mode="json"), right.model_dump(mode="json")],
        }
        for left, right in combinations(eligible, 2)
        if left.author != right.author
    ]
    if not cases:
        raise ValueError("no eligible unassigned intent pairs with distinct authors")
    if any(intent.created_at > captured_at for intent in eligible):
        raise ValueError("an intent timestamp is after capture time")
    if (
        conductor.code_store._git("rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
        != base_sha
    ):
        raise ValueError("code HEAD changed during capture")
    if conductor.store.read().version != state.version:
        raise ValueError("Backbone state changed during capture")
    data = {"schema_version": 1, "sampling": sampling, "cases": cases}
    _write_exclusive(dataset, data)
    try:
        frozen = freeze(dataset, predictions)
    except Exception:
        dataset.unlink()
        raise
    return {
        "case_count": len(cases),
        "base_sha": base_sha,
        "backbone_version": state.version,
        "dataset_sha256": frozen["dataset_sha256"],
        "predictions_sha256": _digest(predictions),
    }


def freeze(dataset: Path, output: Path) -> dict[str, Any]:
    data, cases = _dataset(dataset)
    detector = hashlib.sha256()
    for name in ("conflicts.py", "models.py"):
        detector.update((ROOT / "src" / "backbone_conductor" / name).read_bytes())
    detector.update(Path(__file__).read_bytes())
    frozen = {
        "schema_version": 1,
        "dataset_sha256": _digest(dataset),
        "detector_sha256": detector.hexdigest(),
        "frozen_at": datetime.now(UTC).isoformat(),
        "sampling": data["sampling"],
        "cases": [],
    }
    for case, intents in cases:
        state = BackboneState(intents={intent.id: intent for intent in intents})
        findings = [
            {
                "id": item.id,
                "rule": item.rule,
                "severity": item.severity.value,
                "parties": sorted(item.parties),
                "evidence": item.evidence,
            }
            for item in detect_conflicts(state)
            if not item.resolved
        ]
        frozen["cases"].append({"id": case["id"], "findings": findings})
    _write_exclusive(output, frozen)
    return frozen


def _review_file(
    path: Path,
    dataset_sha: str,
    predictions_sha: str,
    authors: dict[str, set[str]],
) -> tuple[str, dict[str, bool]]:
    data = _read(path)
    if (
        set(data) != {"schema_version", "dataset_sha256", "predictions_sha256", "reviewer", "cases"}
        or data["schema_version"] != 1
    ):
        raise ValueError(f"{path}: review file has an invalid schema")
    if (
        data["dataset_sha256"] != dataset_sha
        or data["predictions_sha256"] != predictions_sha
        or not isinstance(data["cases"], list)
    ):
        raise ValueError(f"{path}: review does not match frozen dataset and predictions")
    reviewer = _nonempty(data["reviewer"], f"{path} reviewer")
    labels: dict[str, bool] = {}
    for item in data["cases"]:
        if not isinstance(item, dict) or set(item) != {"id", "conflict", "rationale"}:
            raise ValueError(f"{path}: each review case needs id, conflict, rationale")
        case_id = _nonempty(item["id"], f"{path} case id")
        if case_id not in authors or case_id in labels:
            raise ValueError(f"{path}: unknown or duplicate case {case_id}")
        if reviewer in authors[case_id]:
            raise ValueError(f"{case_id}: reviewer must differ from intent authors")
        if type(item["conflict"]) is not bool:
            raise ValueError(f"{case_id}: conflict label must be boolean")
        _nonempty(item["rationale"], f"{case_id} rationale")
        labels[case_id] = item["conflict"]
    return reviewer, labels


def score(
    dataset: Path,
    predictions: Path,
    first_review: Path,
    second_review: Path,
    adjudications: Path | None = None,
) -> dict[str, Any]:
    data, cases = _dataset(dataset)
    frozen = _read(predictions)
    if (
        set(frozen)
        != {"schema_version", "dataset_sha256", "detector_sha256", "frozen_at", "sampling", "cases"}
        or frozen["schema_version"] != 1
    ):
        raise ValueError("predictions have an invalid schema")
    dataset_sha = _digest(dataset)
    if frozen["dataset_sha256"] != dataset_sha or frozen["sampling"] != data["sampling"]:
        raise ValueError("predictions do not match the frozen dataset")
    _timestamp(frozen["frozen_at"], "frozen_at")
    if not isinstance(frozen["detector_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", frozen["detector_sha256"]
    ):
        raise ValueError("predictions require a detector SHA-256")
    if not isinstance(frozen["cases"], list) or len(frozen["cases"]) != len(cases):
        raise ValueError("predictions must cover every dataset case")
    predicted: dict[str, bool] = {}
    for (case, intents), item in zip(cases, frozen["cases"], strict=True):
        if not isinstance(item, dict) or set(item) != {"id", "findings"}:
            raise ValueError("prediction case has an invalid schema")
        if item["id"] != case["id"] or not isinstance(item["findings"], list):
            raise ValueError("prediction cases must match dataset order and IDs")
        for finding in item["findings"]:
            if not isinstance(finding, dict) or set(finding) != {
                "id",
                "rule",
                "severity",
                "parties",
                "evidence",
            }:
                raise ValueError(f"{case['id']}: finding has an invalid schema")
            if (
                not isinstance(finding["id"], str)
                or not finding["id"]
                or not isinstance(finding["rule"], str)
                or not finding["rule"]
                or finding["severity"] not in {"advisory", "blocking", "critical"}
                or not isinstance(finding["parties"], list)
                or set(finding["parties"]) != {intent.id for intent in intents}
                or not isinstance(finding["evidence"], dict)
            ):
                raise ValueError(f"{case['id']}: finding does not describe this pair")
        predicted[case["id"]] = bool(item["findings"])

    authors = {case["id"]: {intent.author for intent in intents} for case, intents in cases}
    prediction_sha = _digest(predictions)
    reviewer_a, labels_a = _review_file(first_review, dataset_sha, prediction_sha, authors)
    reviewer_b, labels_b = _review_file(second_review, dataset_sha, prediction_sha, authors)
    if reviewer_a == reviewer_b:
        raise ValueError("two distinct reviewers are required")
    if adjudications is not None:
        adjudicator, adjudicated = _review_file(adjudications, dataset_sha, prediction_sha, authors)
        if adjudicator in {reviewer_a, reviewer_b}:
            raise ValueError("adjudicator must differ from both reviewers")
    else:
        adjudicated = {}

    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    rows = []
    for case, _intents in cases:
        case_id = case["id"]
        values = [labels[case_id] for labels in (labels_a, labels_b) if case_id in labels]
        if len(values) < 2:
            if case_id in adjudicated:
                raise ValueError(f"{case_id}: adjudication requires two disagreeing reviews")
            if not values:
                rows.append(
                    {"id": case_id, "status": "unlabeled", "prediction": predicted[case_id]}
                )
                continue
            rows.append(
                {"id": case_id, "status": "awaiting_review", "prediction": predicted[case_id]}
            )
            continue
        if values[0] == values[1]:
            if case_id in adjudicated:
                raise ValueError(f"{case_id}: agreeing reviews need no adjudication")
            observed, source = values[0], "consensus"
        elif case_id in adjudicated:
            observed = adjudicated[case_id]
            source = "adjudicated"
        else:
            rows.append({"id": case_id, "status": "disputed", "prediction": predicted[case_id]})
            continue
        warning = predicted[case_id]
        outcome = "tp" if warning and observed else "fp" if warning else "fn" if observed else "tn"
        counts[outcome] += 1
        rows.append(
            {
                "id": case_id,
                "project": case["project"],
                "status": source,
                "prediction": warning,
                "label": observed,
                "outcome": outcome,
            }
        )
    resolved = sum(counts.values())
    precision = (
        counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
    )
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    return {
        "status": "complete_sample" if resolved == len(cases) else "incomplete",
        "dataset_sha256": dataset_sha,
        "predictions_sha256": prediction_sha,
        "detector_sha256": frozen["detector_sha256"],
        "sampling": data["sampling"],
        "projects": sorted({case["project"] for case, _intents in cases}),
        "resolved_projects": sorted({row["project"] for row in rows if "project" in row}),
        "sample_count": len(cases),
        "resolved_count": resolved,
        "counts": counts,
        "precision": precision,
        "recall": recall,
        "f1": (
            (2 * precision * recall / (precision + recall) if precision + recall else 0.0)
            if precision is not None and recall is not None
            else None
        ),
        "cases": rows,
        "limitation": LIMITATION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    capture_command = actions.add_parser(
        "capture",
        help="Capture all unassigned intent pairs from a clean Git checkout and freeze them",
    )
    capture_command.add_argument("--repo", type=Path, required=True)
    capture_command.add_argument("--ledger-branch")
    capture_command.add_argument("--project", required=True)
    capture_command.add_argument("--sampling", required=True)
    capture_command.add_argument("--dataset", type=Path, required=True)
    capture_command.add_argument("--predictions", type=Path, required=True)
    freeze_command = actions.add_parser("freeze", help="Freeze predictions before human labeling")
    freeze_command.add_argument("--dataset", type=Path, required=True)
    freeze_command.add_argument("--output", type=Path, required=True)
    score_command = actions.add_parser("score", help="Score a frozen sample against reviews")
    score_command.add_argument("--dataset", type=Path, required=True)
    score_command.add_argument("--predictions", type=Path, required=True)
    score_command.add_argument("--review", action="append", type=Path, required=True)
    score_command.add_argument("--adjudications", type=Path)
    score_command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            result = capture(
                args.repo,
                args.project,
                args.sampling,
                args.dataset,
                args.predictions,
                args.ledger_branch,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.action == "freeze":
            frozen = freeze(args.dataset, args.output)
            print(f"Frozen {len(frozen['cases'])} cases to {args.output}")
            print(f"Dataset SHA-256: {frozen['dataset_sha256']}")
            return 0
        if len(args.review) != 2:
            raise ValueError("score requires exactly two --review files")
        report = score(
            args.dataset, args.predictions, args.review[0], args.review[1], args.adjudications
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"invalid prospective evaluation: {exc}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Prospective sample: {report['resolved_count']}/{report['sample_count']} resolved")
        print(
            f"TP {report['counts']['tp']} | FP {report['counts']['fp']} | FN {report['counts']['fn']} | TN {report['counts']['tn']}"
        )
        precision = "n/a" if report["precision"] is None else f"{report['precision']:.1%}"
        recall = "n/a" if report["recall"] is None else f"{report['recall']:.1%}"
        print(f"Precision {precision} | Recall {recall}")
        print(report["limitation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
