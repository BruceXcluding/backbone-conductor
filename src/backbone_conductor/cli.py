"""Command line interface for a repository's local Backbone ledger."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .service import Conductor
from .storage import AUDIT_EVENT_TYPES


def _json_file(filename: str) -> dict[str, Any]:
    text = sys.stdin.read() if filename == "-" else Path(filename).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("JSON input must be an object")
    return value


def _validate_tls_key(filename: str, repo: str) -> None:
    """Keep the server's private key out of the ledger and other users' reach."""
    key = Path(filename).expanduser().absolute()
    if key.is_symlink():
        raise ValueError("TLS private key must be a regular file, not a symlink")
    resolved = key.resolve(strict=True)
    if resolved.is_relative_to(Path(repo).expanduser().resolve()):
        raise ValueError("TLS private key must be outside the repository")
    mode = key.stat(follow_symlinks=False).st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("TLS private key must be a regular file")
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("TLS private key must be accessible only to its owner (0600)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backbone", description="Git-native intent and decision coordination."
    )
    parser.add_argument(
        "--repo", default=".", help="Git repository path (default: current directory)"
    )
    parser.add_argument(
        "--ledger-branch", help="Use the separate backbone metadata branch worktree"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ledger = commands.add_parser("ledger", help="Manage a separate metadata branch")
    ledger_actions = ledger.add_subparsers(dest="action", required=True)
    ledger_actions.add_parser("create", help="Create a metadata-only backbone branch")
    ledger_actions.add_parser("migrate", help="Move a quiescent inline ledger with Git history")
    attach = ledger_actions.add_parser("attach", help="Attach a fetched backbone branch")
    attach.add_argument("--remote", default="origin")
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
            replace = group.add_parser(
                "replace", help="Draft an audited replacement for an accepted intent"
            )
            replace.add_argument("id")
            replace.add_argument("--file", required=True, help="JSON patch file, or - for stdin")
            replace.add_argument("--author", required=True)
            replace.add_argument("--reason", required=True)
            replace.add_argument(
                "--version", required=True, help="Backbone version observed before editing"
            )
            review = group.add_parser("review", help="Accept or reject a draft with a rationale")
            review.add_argument("id")
            review.add_argument("--outcome", required=True, choices=["accepted", "rejected"])
            review.add_argument("--author", required=True)
            review.add_argument("--rationale", required=True)
            review.add_argument(
                "--version", required=True, help="Backbone version observed before review"
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
    refresh = commands.add_parser("refresh", help="Fetch and fast-forward from the Git remote")
    refresh.add_argument("--remote", default="origin")
    refresh.add_argument("--branch")
    reconcile = commands.add_parser("reconcile", help="Merge reviewed Backbone metadata")
    reconcile.add_argument("--remote", default="origin")
    reconcile.add_argument("--branch")
    reconcile.add_argument("--local-head", required=True)
    reconcile.add_argument("--remote-head", required=True)
    reconcile.add_argument("--author", required=True)
    reconcile.add_argument("--rationale", required=True)
    reconcile.add_argument(
        "--resolutions-file", help="JSON decisions for every competing metadata object"
    )
    updates = commands.add_parser("updates", help="Check ledger changes affecting a member")
    updates.add_argument("--member")
    updates.add_argument("--since-version")
    log = commands.add_parser("log")
    log.add_argument("--limit", type=int, default=50)
    log.add_argument("--author", help="Exact Git author name")
    log.add_argument("--http-principal", help="Exact authenticated HTTP principal")
    log.add_argument("--type", dest="event_type", choices=AUDIT_EVENT_TYPES)
    log.add_argument("--since", help="Inclusive ISO 8601 author timestamp with timezone")
    log.add_argument("--until", help="Inclusive ISO 8601 author timestamp with timezone")
    audit = commands.add_parser("audit", help="Inspect Git audit commit signatures")
    audit_actions = audit.add_subparsers(dest="action", required=True)
    verify = audit_actions.add_parser("verify", help="Verify recent Backbone commit signatures")
    verify.add_argument("--limit", type=int, default=50)
    verify.add_argument(
        "--require-signatures",
        action="store_true",
        help="Exit nonzero unless all inspected commits have valid signatures",
    )
    commands.add_parser("schema", help="Print protocol JSON Schema")
    review = commands.add_parser("review", help="Request advisory semantic review through DSH")
    review.add_argument("task_id")
    review.add_argument("--dsh-home", required=True, help="Path to the configured DSH home")
    review.add_argument("--model", required=True)
    review.add_argument("--provider", default="deepseek-official")
    review.add_argument(
        "--attempt-log", help="Private JSONL log outside the repository for failed DSH reviews"
    )
    dsh = commands.add_parser("dsh", help="Run a member-scoped DSH agent with Backbone MCP")
    dsh.add_argument("--member", required=True)
    dsh.add_argument("--workspace", required=True, help="Separate coding workspace or worktree")
    dsh.add_argument(
        "--dsh-home", required=True, help="Dedicated DSH home outside both repositories"
    )
    dsh.add_argument("--model", required=True)
    dsh.add_argument("--provider", default="deepseek-official")
    dsh.add_argument("--session-id", help="Continue an existing DSH session in this home")
    dsh.add_argument("--mcp-url", help="Authenticated remote coordinator /mcp URL")
    dsh.add_argument("--mcp-token-file", help="Private file containing this member's bearer token")
    dsh.add_argument("--mcp-ca-file", help="CA certificate for a remote HTTPS coordinator")
    dsh_prompt = dsh.add_mutually_exclusive_group(required=True)
    dsh_prompt.add_argument("--prompt")
    dsh_prompt.add_argument("--prompt-file", help="UTF-8 prompt file")

    serve = commands.add_parser("serve", help="Run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--auth-file", help="Private JSON file of bearer-token digests")
    serve.add_argument(
        "--mcp-http", action="store_true", help="Expose bearer-authenticated member MCP at /mcp"
    )
    serve.add_argument(
        "--mcp-allowed-host",
        action="append",
        default=[],
        help="Additional public Host header accepted by MCP (repeatable)",
    )
    serve.add_argument("--tls-certfile", help="PEM certificate for direct HTTPS")
    serve.add_argument("--tls-keyfile", help="PEM private key for direct HTTPS")
    auth = commands.add_parser("auth", help="Create a private HTTP token-digest file")
    auth_commands = auth.add_subparsers(dest="action", required=True)
    create_auth = auth_commands.add_parser("create")
    create_auth.add_argument("--file", required=True, help="New file outside the Git repository")
    create_auth.add_argument("--admin", required=True, help="Administrator principal name")
    create_auth.add_argument("--member", action="append", default=[], help="Member principal name")
    create_auth.add_argument(
        "--reviewer", action="append", default=[], help="Reviewer principal name"
    )
    rotate_auth = auth_commands.add_parser("rotate", help="Replace tokens without restarting HTTP")
    rotate_auth.add_argument("--file", required=True, help="Existing private token file")
    rotate_auth.add_argument("--admin", required=True, help="Administrator principal name")
    rotate_auth.add_argument("--member", action="append", default=[], help="Member principal name")
    rotate_auth.add_argument(
        "--reviewer", action="append", default=[], help="Reviewer principal name"
    )
    mcp = commands.add_parser("mcp", help="Run the MCP server over stdio")
    mcp.add_argument("--member", help="Bind member operations and omit administrator tools")
    return parser


def _run(args: argparse.Namespace) -> Any:
    if args.command == "ledger":
        from .ledger import attach_ledger, create_ledger, migrate_ledger

        if args.ledger_branch is not None:
            raise ValueError("Ledger setup uses --repo only; omit --ledger-branch")
        if args.action == "create":
            return create_ledger(args.repo)
        if args.action == "migrate":
            return migrate_ledger(args.repo)
        return attach_ledger(args.repo, args.remote)
    if args.command == "schema":
        from .models import BackboneState

        return BackboneState.model_json_schema()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        mcp_setting = os.environ.get("BACKBONE_MCP_HTTP", "0")
        if mcp_setting not in {"0", "1"}:
            raise ValueError("BACKBONE_MCP_HTTP must be 0 or 1")
        mcp_http = args.mcp_http or mcp_setting == "1"
        env_hosts = os.environ.get("BACKBONE_MCP_ALLOWED_HOSTS", "")
        mcp_allowed_hosts = [*args.mcp_allowed_host]
        if env_hosts:
            mcp_allowed_hosts.extend(host.strip() for host in env_hosts.split(","))
        if args.host not in {"127.0.0.1", "::1", "localhost"} and not args.auth_file:
            raise ValueError("Non-loopback HTTP binding requires --auth-file")
        if mcp_http and not args.auth_file:
            raise ValueError("Streamable HTTP MCP requires --auth-file")
        if mcp_allowed_hosts and not mcp_http:
            raise ValueError("MCP allowed hosts require --mcp-http or BACKBONE_MCP_HTTP=1")
        if any(
            not host.strip()
            or "/" in host
            or "@" in host
            or "*" in host
            or any(char.isspace() for char in host)
            for host in mcp_allowed_hosts
        ):
            raise ValueError("MCP allowed hosts must be Host header values, not URLs")
        if bool(args.tls_certfile) != bool(args.tls_keyfile):
            raise ValueError("Direct HTTPS requires both --tls-certfile and --tls-keyfile")
        if args.tls_keyfile:
            _validate_tls_key(args.tls_keyfile, args.repo)
        uvicorn.run(
            create_app(
                args.repo,
                auth_file=args.auth_file,
                ledger_branch=args.ledger_branch,
                mcp_http=mcp_http,
                mcp_allowed_hosts=tuple(mcp_allowed_hosts),
            ),
            host=args.host,
            port=args.port,
            ssl_certfile=args.tls_certfile,
            ssl_keyfile=args.tls_keyfile,
        )
        return None
    if args.command == "auth":
        from .auth import create_token_file, rotate_token_file

        conductor = Conductor(args.repo, ledger_branch=args.ledger_branch)
        return {
            "file": args.file,
            "credentials": (
                create_token_file(
                    args.file, conductor.code_store.root, args.admin, args.member, args.reviewer
                )
                if args.action == "create"
                else rotate_token_file(
                    args.file, conductor.code_store.root, args.admin, args.member, args.reviewer
                )
            ),
            "detail": "Save these plaintext tokens now; only SHA-256 digests are stored in the file.",
        }
    if args.command == "mcp":
        from .mcp_server import create_server

        create_server(args.repo, member_id=args.member, ledger_branch=args.ledger_branch).run(
            transport="stdio"
        )
        return None
    if args.command == "dsh":
        from .dsh_agent import DSHMemberRunner, DSHRemoteMemberRunner

        prompt = (
            Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt
        )
        if args.mcp_url:
            if not args.mcp_token_file:
                raise ValueError("Remote DSH requires --mcp-token-file")
            if args.ledger_branch:
                raise ValueError("Remote DSH does not use --ledger-branch")
            return DSHRemoteMemberRunner(
                args.workspace,
                args.dsh_home,
                args.member,
                args.model,
                args.mcp_url,
                args.mcp_token_file,
                args.provider,
                ca_file=args.mcp_ca_file,
            ).run(prompt, session_id=args.session_id)
        if args.mcp_token_file or args.mcp_ca_file:
            raise ValueError("--mcp-token-file and --mcp-ca-file require --mcp-url")
        return DSHMemberRunner(
            args.repo,
            args.workspace,
            args.dsh_home,
            args.member,
            args.model,
            args.provider,
            ledger_branch=args.ledger_branch,
        ).run(prompt, session_id=args.session_id)

    conductor = Conductor(args.repo, ledger_branch=args.ledger_branch)
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
        if args.command == "intent" and args.action == "replace":
            return conductor.replace_intent(
                args.id, _json_file(args.file), args.author, args.reason, args.version
            )
        if args.command == "intent" and args.action == "review":
            return conductor.review_intent(
                args.id, args.outcome, args.author, args.rationale, args.version
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
    if args.command == "refresh":
        return conductor.refresh(args.remote, args.branch)
    if args.command == "reconcile":
        return conductor.reconcile(
            args.local_head,
            args.remote_head,
            args.author,
            args.rationale,
            args.remote,
            args.branch,
            _json_file(args.resolutions_file) if args.resolutions_file else None,
        )
    if args.command == "updates":
        return conductor.check_backbone_sync(args.member, args.since_version)
    if args.command == "review":
        return conductor.review_task(
            args.task_id, args.dsh_home, args.model, args.provider, attempt_log=args.attempt_log
        )
    if args.command == "log":
        if not 1 <= args.limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        return conductor.log(
            args.limit,
            author=args.author,
            http_principal=args.http_principal,
            event_type=args.event_type,
            since=args.since,
            until=args.until,
        )
    if args.command == "audit":
        return conductor.verify_audit_signatures(args.limit)
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
    if args.command == "audit" and args.action == "verify":
        return int(
            result["invalid"] > 0
            or (args.require_signatures and not result["all_inspected_signed_and_valid"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
