"""Official MCP SDK stdio interface, optionally bound to one local member."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .service import Conductor


def create_server(
    repo: str | Path,
    member_id: str | None = None,
    *,
    ledger_branch: str | None = None,
    member_resolver: Callable[[], str] | None = None,
    http_allowed_hosts: tuple[str, ...] | None = None,
) -> FastMCP:
    """Create stdio tools or request-bound member tools for authenticated HTTP."""
    if member_id is not None and member_resolver is not None:
        raise ValueError("Use either a fixed member or a request-bound member resolver")
    if http_allowed_hosts is not None and member_resolver is None:
        raise ValueError("HTTP MCP requires a request-bound member resolver")
    if member_id is not None and not member_id.strip():
        raise ValueError("member_id must not be blank")
    bound_member = member_id is not None or member_resolver is not None
    conductor = Conductor(repo, ledger_branch=ledger_branch)
    http_options = {}
    if http_allowed_hosts is not None:
        http_options = {
            "stateless_http": True,
            "json_response": True,
            "transport_security": TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(http_allowed_hosts),
                allowed_origins=[
                    "http://127.0.0.1:*",
                    "http://localhost:*",
                    "http://[::1]:*",
                ],
            ),
        }
    server = FastMCP(
        "Backbone Conductor",
        instructions=(
            "Git-native coordination for the configured repository. "
            "Member-bound servers cannot arbitrate, dispatch, approve, or transition objects. "
            "Artifact checks are deterministic; semantic review requires a human."
        ),
        **http_options,
    )

    def current_member() -> str:
        selected = member_resolver() if member_resolver is not None else member_id
        if selected is None:
            raise PermissionError("No authenticated member is bound to this request")
        return selected

    def member(requested: str | None) -> str:
        if bound_member:
            selected = current_member()
            if requested is not None and requested != selected:
                raise PermissionError("member_id does not match this server's bound member")
            return selected
        if requested is None or not requested.strip():
            raise ValueError("member_id is required on an unbound server")
        return requested

    def authored(data: dict[str, Any], initial_status: str) -> dict[str, Any]:
        result = dict(data)
        if bound_member:
            selected = current_member()
            if result.get("author", selected) != selected:
                raise PermissionError("author does not match this server's bound member")
            if result.get("status", initial_status) != initial_status:
                raise PermissionError(f"Members may only create objects in {initial_status} status")
            result["author"] = selected
        return result

    @server.tool()
    def get_my_task(member_id: str | None = None) -> dict:
        """Get assigned task context; member_id is optional when this server is member-bound."""
        return conductor.get_my_task(member(member_id))

    @server.tool()
    def submit_artifact(artifact: dict[str, Any], member_id: str | None = None) -> dict:
        """Submit a committed task artifact for deterministic checks and human semantic review."""
        return conductor.submit_artifact(member(member_id), artifact)

    @server.tool()
    def check_backbone_sync(member_id: str | None = None, since_version: str | None = None) -> dict:
        """Report ledger changes and relevant accepted decisions since a known version."""
        selected = member(member_id) if bound_member or member_id is not None else None
        return conductor.check_backbone_sync(selected, since_version)

    @server.tool()
    def create_intent(intent_data: dict[str, Any]) -> dict:
        """Propose a draft intent; member-bound servers bind its author automatically."""
        return conductor.create_intent(authored(intent_data, "draft"))

    @server.tool()
    def log_decision(decision_data: dict[str, Any]) -> dict:
        """Propose a decision with rationale; member-bound servers bind its author automatically."""
        return conductor.log_decision(authored(decision_data, "proposed"))

    @server.tool()
    def start_task(task_id: str, member_id: str | None = None) -> dict:
        """Start an assigned task; ownership is checked against the selected member."""
        return conductor.start_task(task_id, member(member_id))

    @server.tool()
    def rebase_task(task_id: str, expected_version: str, member_id: str | None = None) -> dict:
        """Refresh an assigned task's decisions and target branch; resubmission is required."""
        return conductor.rebase_task(task_id, member(member_id), expected_version)

    if not bound_member:

        @server.tool()
        def revise_intent(
            intent_id: str, patch: dict[str, Any], author: str, expected_version: str
        ) -> dict:
            """Administrator: revise an undispatched intent and return it to draft."""
            return conductor.revise_intent(intent_id, patch, author, expected_version)

        @server.tool()
        def replace_intent(
            intent_id: str, patch: dict[str, Any], author: str, reason: str, expected_version: str
        ) -> dict:
            """Administrator: draft a linked replacement for accepted work after cancelling tasks."""
            return conductor.replace_intent(intent_id, patch, author, reason, expected_version)

        @server.tool()
        def review_intent(
            intent_id: str, outcome: str, reviewer: str, rationale: str, expected_version: str
        ) -> dict:
            """Administrator: record a version-bound human acceptance or rejection of a draft."""
            return conductor.review_intent(
                intent_id, outcome, reviewer, rationale, expected_version
            )

        @server.tool()
        def cancel_task(task_id: str, author: str, reason: str) -> dict:
            """Administrator: cancel active work, recording the reason and reopening its intent."""
            return conductor.cancel_task(task_id, author, reason)

        @server.tool()
        def dispatch_task(
            intent_id: str,
            member_id: str,
            spec: str = "",
            forbidden_paths: list[str] | None = None,
        ) -> dict:
            """Administrator: dispatch an accepted intent with constraints and context."""
            return conductor.dispatch_task(intent_id, member_id, spec, forbidden_paths)

        @server.tool()
        def transition_intent(intent_id: str, status: str) -> dict:
            """Administrator: change intent status using the protocol state machine."""
            return conductor.transition_intent(intent_id, status)

        @server.tool()
        def transition_decision(decision_id: str, status: str) -> dict:
            """Administrator: accept, supersede, or revert a decision."""
            return conductor.transition_decision(decision_id, status)

        @server.tool()
        def detect_conflicts() -> dict:
            """Administrator: detect and record deterministic scope and decision conflicts."""
            return conductor.detect_conflicts()

        @server.tool()
        def verify_audit_signatures(limit: int = 50) -> dict:
            """Administrator: verify recent Backbone Git commit signatures."""
            return conductor.verify_audit_signatures(limit)

        @server.tool()
        def resolve_conflict(conflict_id: str, author: str, action: str, rationale: str) -> dict:
            """Administrator: record an explicit human arbitration with its rationale."""
            return conductor.resolve_conflict(conflict_id, author, action, rationale)

        @server.tool()
        def merge_task(task_id: str, author: str, rationale: str | None = None) -> dict:
            """Administrator: record human approval after the actual Git merge has occurred."""
            return conductor.merge_task(task_id, author, rationale)

        @server.tool()
        def refresh_backbone(remote: str = "origin", branch: str | None = None) -> dict:
            """Administrator: fetch peer history and fast-forward, or report divergence."""
            return conductor.refresh(remote, branch)

        @server.tool()
        def reconcile_backbone(
            local_head: str,
            remote_head: str,
            author: str,
            rationale: str,
            remote: str = "origin",
            branch: str | None = None,
            resolutions: dict[str, dict[str, dict[str, Any]]] | None = None,
        ) -> dict:
            """Administrator: merge reviewed metadata histories with two Git parents."""
            return conductor.reconcile(
                local_head, remote_head, author, rationale, remote, branch, resolutions
            )

    return server
