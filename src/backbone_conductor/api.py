"""HTTP API with optional bearer authentication and member authorization."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .auth import Principal, TokenAuth
from .service import Conductor


def _member_route(method: str, path: str) -> bool:
    if (method, path) in {
        ("GET", "/schema"),
        ("GET", "/tasks"),
        ("GET", "/sync"),
        ("POST", "/intents"),
        ("POST", "/decisions"),
        ("POST", "/artifacts"),
    }:
        return True
    if method == "GET":
        return re.fullmatch(r"/tasks/[^/]+", path) is not None
    if method == "POST":
        return re.fullmatch(r"/tasks/[^/]+/(start|rebase|submit)", path) is not None
    return False


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transition(Action):
    status: str = Field(min_length=1)


class Dispatch(Action):
    intent_id: str = Field(min_length=1)
    member_id: str = Field(min_length=1)
    spec: str = ""
    forbidden_paths: list[str] = Field(default_factory=list)


class Member(Action):
    member_id: str = Field(min_length=1)


class Submission(Member):
    artifact: dict[str, Any]


class Approval(Action):
    author: str = Field(min_length=1)
    rationale: str | None = None


class IntentRevision(Approval):
    patch: dict[str, Any]
    expected_version: str = Field(min_length=1)


class Cancellation(Approval):
    reason: str = Field(min_length=1)


class TaskRebase(Member):
    expected_version: str = Field(min_length=1)


class Resolution(Approval):
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Sync(Action):
    remote: str = "origin"
    branch: str | None = None


class Reconciliation(Sync):
    local_head: str = Field(min_length=1)
    remote_head: str = Field(min_length=1)
    author: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    resolutions: dict[str, dict[str, dict[str, Any]]] | None = None


def create_app(
    repo: str | Path,
    *,
    auth_file: str | Path | None = None,
    ledger_branch: str | None = None,
) -> FastAPI:
    """Create a local admin API or an authenticated admin/member API."""
    conductor = Conductor(repo, ledger_branch=ledger_branch)
    auth = TokenAuth(auth_file, conductor.code_store.root) if auth_file is not None else None
    app = FastAPI(
        title="Backbone Conductor",
        version=__version__,
        description=(
            "Without --auth-file, bind to loopback for trusted local administrators. "
            "With --auth-file, bearer tokens authorize admin and bound member operations. "
            "Use TLS at a trusted reverse proxy for remote access. "
            "Merge approval records require an actual Git merge and human semantic review."
        ),
    )
    app.state.conductor = conductor

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if auth is None:
            request.state.principal = Principal("local", "admin")
        elif request.url.path == "/health":
            request.state.principal = None
        else:
            principal = auth.authenticate(request.headers.get("authorization"))
            if principal is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Valid bearer token required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.principal = principal
            if principal.role == "member" and not _member_route(request.method, request.url.path):
                return JSONResponse(status_code=403, content={"detail": "Admin role required"})
        return await call_next(request)

    def bind_member(request: Request, member_id: str | None) -> str | None:
        principal = request.state.principal
        if principal.role == "member":
            if member_id is not None and member_id != principal.name:
                raise PermissionError("Member identity is bound to the bearer token")
            return principal.name
        return member_id

    def bind_author(request: Request, data: dict[str, Any], required_status: str) -> dict:
        principal = request.state.principal
        if auth is None:
            return data
        if data.get("author", principal.name) != principal.name:
            raise PermissionError("Author identity is bound to the bearer token")
        if principal.role == "member" and data.get("status", required_status) != required_status:
            raise PermissionError(f"Members may create {required_status} records only")
        return {**data, "author": principal.name}

    def actor(request: Request, claimed: str) -> str:
        if auth is not None and claimed != request.state.principal.name:
            raise PermissionError("Author identity is bound to the bearer token")
        return claimed

    def visible_task(request: Request, task_id: str) -> dict:
        result = conductor.state()["tasks"][task_id]
        bind_member(request, result["member_id"])
        return result

    async def domain_error(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, PermissionError):
            status = 403
        elif isinstance(exc, (KeyError, FileNotFoundError)):
            status = 404
        elif isinstance(exc, ValueError):
            status = 422
        else:
            status = 409
        message = str(exc.args[0]) if isinstance(exc, KeyError) else str(exc)
        return JSONResponse(status_code=status, content={"detail": message})

    for error in (ValueError, KeyError, PermissionError, FileNotFoundError, RuntimeError):
        app.add_exception_handler(error, domain_error)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/initialize")
    def initialize() -> dict:
        return conductor.initialize()

    @app.get("/state")
    def state() -> dict:
        return conductor.state()

    @app.get("/schema")
    def schema() -> dict:
        from .models import BackboneState

        return BackboneState.model_json_schema()

    @app.get("/intents")
    def intents() -> list[dict]:
        return list(conductor.state()["intents"].values())

    @app.post("/intents", status_code=201)
    def create_intent(data: dict[str, Any], request: Request) -> dict:
        return conductor.create_intent(bind_author(request, data, "draft"))

    @app.get("/intents/{intent_id}")
    def intent(intent_id: str) -> dict:
        return conductor.state()["intents"][intent_id]

    @app.post("/intents/{intent_id}/transition")
    def transition_intent(intent_id: str, data: Transition) -> dict:
        return conductor.transition_intent(intent_id, data.status)

    @app.post("/intents/{intent_id}/revise")
    def revise_intent(intent_id: str, data: IntentRevision, request: Request) -> dict:
        return conductor.revise_intent(
            intent_id, data.patch, actor(request, data.author), data.expected_version
        )

    @app.get("/decisions")
    def decisions() -> list[dict]:
        return list(conductor.state()["decisions"].values())

    @app.post("/decisions", status_code=201)
    def create_decision(data: dict[str, Any], request: Request) -> dict:
        return conductor.log_decision(bind_author(request, data, "proposed"))

    @app.get("/decisions/{decision_id}")
    def decision(decision_id: str) -> dict:
        return conductor.state()["decisions"][decision_id]

    @app.post("/decisions/{decision_id}/transition")
    def transition_decision(decision_id: str, data: Transition) -> dict:
        return conductor.transition_decision(decision_id, data.status)

    @app.get("/tasks")
    def tasks(request: Request, member_id: str | None = None) -> dict:
        member_id = bind_member(request, member_id)
        if member_id is not None:
            return conductor.get_my_task(member_id)
        return {"tasks": list(conductor.state()["tasks"].values())}

    @app.post("/tasks", status_code=201)
    def dispatch_task(data: Dispatch) -> dict:
        return conductor.dispatch_task(
            data.intent_id, data.member_id, data.spec, data.forbidden_paths
        )

    @app.get("/tasks/{task_id}")
    def task(task_id: str, request: Request) -> dict:
        return visible_task(request, task_id)

    @app.post("/tasks/{task_id}/start")
    def start_task(task_id: str, data: Member, request: Request) -> dict:
        return conductor.start_task(task_id, bind_member(request, data.member_id))

    @app.post("/tasks/{task_id}/rebase")
    def rebase_task(task_id: str, data: TaskRebase, request: Request) -> dict:
        return conductor.rebase_task(
            task_id, bind_member(request, data.member_id), data.expected_version
        )

    @app.post("/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, data: Cancellation, request: Request) -> dict:
        return conductor.cancel_task(task_id, actor(request, data.author), data.reason)

    @app.post("/artifacts", status_code=201)
    def submit_artifact(data: Submission, request: Request) -> dict:
        return conductor.submit_artifact(bind_member(request, data.member_id), data.artifact)

    @app.post("/tasks/{task_id}/submit")
    def submit_task(task_id: str, data: Submission, request: Request) -> dict:
        assigned = visible_task(request, task_id)
        bind_member(request, data.member_id)
        if assigned["member_id"] != data.member_id:
            raise PermissionError("Task belongs to another member")
        artifact = dict(data.artifact)
        if artifact.get("intent_id", assigned["intent_id"]) != assigned["intent_id"]:
            raise ValueError("artifact.intent_id must match the task in the request path")
        artifact["intent_id"] = assigned["intent_id"]
        return conductor.submit_artifact(data.member_id, artifact)

    @app.post("/tasks/{task_id}/merge")
    def merge_task(task_id: str, data: Approval, request: Request) -> dict:
        """Record human approval after performing the actual Git merge externally."""
        return conductor.merge_task(task_id, actor(request, data.author), data.rationale)

    @app.get("/conflicts")
    def conflicts() -> list[dict]:
        return list(conductor.state()["conflicts"].values())

    @app.post("/conflicts/check")
    def detect_conflicts() -> dict:
        return conductor.detect_conflicts()

    @app.post("/conflicts/{conflict_id}/resolve")
    def resolve_conflict(conflict_id: str, data: Resolution, request: Request) -> dict:
        return conductor.resolve_conflict(
            conflict_id, actor(request, data.author), data.action, data.rationale
        )

    @app.get("/sync")
    def check_sync(
        request: Request, member_id: str | None = None, since_version: str | None = None
    ) -> dict:
        return conductor.check_backbone_sync(bind_member(request, member_id), since_version)

    @app.post("/sync")
    def sync(data: Sync) -> dict:
        return conductor.sync(data.remote, data.branch)

    @app.post("/refresh")
    def refresh(data: Sync) -> dict:
        return conductor.refresh(data.remote, data.branch)

    @app.post("/reconcile")
    def reconcile(data: Reconciliation, request: Request) -> dict:
        return conductor.reconcile(
            data.local_head,
            data.remote_head,
            actor(request, data.author),
            data.rationale,
            data.remote,
            data.branch,
            data.resolutions,
        )

    @app.get("/timeline")
    def timeline(limit: int = Query(default=50, ge=1, le=1000)) -> list[dict]:
        return conductor.log(limit)

    return app
