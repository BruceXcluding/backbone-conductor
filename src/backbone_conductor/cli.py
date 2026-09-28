"""Command line interface for a repository's local Backbone ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .service import Conductor


def _json_file(filename: str) -> dict[str, Any]:
    text = sys.stdin.read() if filename == "-" else Path(filename).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backbone", description="Git-native intent and decision coordination."
    )
    parser.add_argument(
        "--repo", default=".", help="Git repository path (default: current directory)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize the Backbone ledger in an existing Git repository")
    commands.add_parser("status", help="Print the complete ledger state")
    for kind in ("intent", "decision"):
        group = commands.add_parser(kind).add_subparsers(dest="action", required=True)
        create = group.add_parser("create")
        create.add_argument("--file", required=True, help="JSON object file, or - for stdin")
        transition = group.add_parser("transition")
        transition.add_argument("id")
        transition.add_argument("status")
        group.add_parser("list")
        if kind == "intent":
            revise = group.add_parser("revise", help="Revise an undispatched intent")
            revise.add_argument("id")
            revise.add_argument("--file", required=True, help="JSON patch file, or - for stdin")
            revise.add_argument("--author", required=True)
            revise.add_argument(
                "--version", required=True, help="Backbone version observed before editing"
            )

    tasks = commands.add_parser("task").add_subparsers(dest="action", required=True)
    dispatch = tasks.add_parser("dispatch", help="Assign an accepted intent to a member")
    dispatch.add_argument("intent_id")
    dispatch.add_argument("--member", required=True)
    spec = dispatch.add_mutually_exclusive_group()
    spec.add_argument("--spec", default="", help="Task specification text")
    spec.add_argument("--spec-file", help="Read the task specification from this file")
    dispatch.add_argument(
        "--forbid", action="append", default=[], help="Forbidden path (repeatable)"
    )
    listing = tasks.add_parser("list")
    listing.add_argument("--member", required=True)
    start = tasks.add_parser("start")
    start.add_argument("task_id")
    start.add_argument("--member", required=True)
    submit = tasks.add_parser("submit")
    submit.add_argument("--member", required=True)
    submit.add_argument("--file", required=True, help="Artifact JSON object, or - for stdin")
    merge = tasks.add_parser(
        "merge", help="Record human approval after the artifact has been merged with Git"
    )
    merge.add_argument("task_id")
    merge.add_argument("--author", required=True)
    merge.add_argument(
        "--rationale", help="Required when accepted decisions changed after submission"
    )
    cancel = tasks.add_parser("cancel", help="Cancel active work with an audited reason")
    cancel.add_argument("task_id")
    cancel.add_argument("--author", required=True)
    cancel.add_argument("--reason", required=True)
    rebase = tasks.add_parser("rebase", help="Refresh task context without changing code")
    rebase.add_argument("task_id")
    rebase.add_argument("--member", required=True)
    rebase.add_argument("--version", required=True, help="Backbone version observed before refresh")

    conflicts = commands.add_parser("conflict").add_subparsers(dest="action", required=True)
    conflicts.add_parser("check", help="Detect and record deterministic conflicts")
    conflicts.add_parser("list")
    resolve = conflicts.add_parser("resolve")
    resolve.add_argument("conflict_id")
    resolve.add_argument("--author", required=True)
    resolve.add_argument("--action", dest="resolution_action", required=True)
    resolve.add_argument("--rationale", required=True)

    sync = commands.add_parser("sync", help="Synchronize with the configured Git remote")
    sync.add_argument("--remote", default="origin")
    sync.add_argument("--branch")
    updates = commands.add_parser("updates", help="Check ledger changes affecting a member")
    updates.add_argument("--member")
    updates.add_argument("--since-version")
    log = commands.add_parser("log")
    log.add_argument("--limit", type=int, default=50)
    commands.add_parser("schema", help="Print protocol JSON Schema")
    review = commands.add_parser("review", help="Request advisory semantic review through DSH")
    review.add_argument("task_id")
    review.add_argument("--dsh-home", required=True, help="Path to the configured DSH home")
    review.add_argument("--model", required=True)
    review.add_argument("--provider", default="deepseek-official")

    serve = commands.add_parser("serve", help="Run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--auth-file", help="Private JSON file of bearer-token digests")
    auth = commands.add_parser("auth", help="Create a private HTTP token-digest file")
    auth_commands = auth.add_subparsers(dest="action", required=True)
    create_auth = auth_commands.add_parser("create")
    create_auth.add_argument("--file", required=True, help="New file outside the Git repository")
    create_auth.add_argument("--admin", required=True, help="Administrator principal name")
    create_auth.add_argument("--member", action="append", default=[], help="Member principal name")
    mcp = commands.add_parser("mcp", help="Run the MCP server over stdio")
    mcp.add_argument("--member", help="Bind member operations and omit administrator tools")
    return parser


def _run(args: argparse.Namespace) -> Any:
    if args.command == "schema":
        from .models import BackboneState

        return BackboneState.model_json_schema()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        if args.host not in {"127.0.0.1", "::1", "localhost"} and not args.auth_file:
            raise ValueError("Non-loopback HTTP binding requires --auth-file")
        uvicorn.run(create_app(args.repo, auth_file=args.auth_file), host=args.host, port=args.port)
        return None
    if args.command == "auth":
        from .auth import create_token_file

        conductor = Conductor(args.repo)
        return {
            "file": args.file,
            "credentials": create_token_file(
                args.file, conductor.store.root, args.admin, args.member
            ),
            "detail": "Save these plaintext tokens now; only SHA-256 digests are stored in the file.",
        }
    if args.command == "mcp":
        from .mcp_server import create_server

        create_server(args.repo, member_id=args.member).run(transport="stdio")
        return None

    conductor = Conductor(args.repo)
    if args.command == "init":
        return conductor.initialize()
    if args.command == "status":
        return conductor.state()
    if args.command in {"intent", "decision"}:
        if args.action == "list":
            return list(conductor.state()[f"{args.command}s"].values())
        if args.action == "create":
            method = conductor.create_intent if args.command == "intent" else conductor.log_decision
            return method(_json_file(args.file))
        if args.command == "intent" and args.action == "revise":
            return conductor.revise_intent(
                args.id, _json_file(args.file), args.author, args.version
            )
        method = (
            conductor.transition_intent
            if args.command == "intent"
            else conductor.transition_decision
        )
        return method(args.id, args.status)
    if args.command == "task":
        if args.action == "dispatch":
            spec = Path(args.spec_file).read_text(encoding="utf-8") if args.spec_file else args.spec
            return conductor.dispatch_task(args.intent_id, args.member, spec, args.forbid)
        if args.action == "list":
            return conductor.get_my_task(args.member)
        if args.action == "start":
            return conductor.start_task(args.task_id, args.member)
        if args.action == "submit":
            return conductor.submit_artifact(args.member, _json_file(args.file))
        if args.action == "cancel":
            return conductor.cancel_task(args.task_id, args.author, args.reason)
        if args.action == "rebase":
            return conductor.rebase_task(args.task_id, args.member, args.version)
        return conductor.merge_task(args.task_id, args.author, args.rationale)
    if args.command == "conflict":
        if args.action == "check":
            return conductor.detect_conflicts()
        if args.action == "list":
            return list(conductor.state()["conflicts"].values())
        return conductor.resolve_conflict(
            args.conflict_id, args.author, args.resolution_action, args.rationale
        )
    if args.command == "sync":
        return conductor.sync(args.remote, args.branch)
    if args.command == "updates":
        return conductor.check_backbone_sync(args.member, args.since_version)
    if args.command == "review":
        return conductor.review_task(args.task_id, args.dsh_home, args.model, args.provider)
    if args.command == "log":
        if not 1 <= args.limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        return conductor.log(args.limit)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = _run(args)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        message = str(exc.args[0]) if isinstance(exc, KeyError) else str(exc)
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
