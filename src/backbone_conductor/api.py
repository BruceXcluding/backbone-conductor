"""HTTP API for a trusted local administrator; this is not an authentication boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .service import Conductor


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


class Resolution(Approval):
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class Sync(Action):
    remote: str = "origin"
    branch: str | None = None


def create_app(repo: str | Path) -> FastAPI:
    """Create a local API. Callers providing remote access must supply authentication."""
    conductor = Conductor(repo)
    app = FastAPI(
        title="Backbone Conductor",
        version="0.1.0",
        description=(
            "Trusted local administrator API. No built-in authentication; bind to loopback. "
            "Merge approval records require an actual Git merge and human semantic review."
        ),
    )
    app.state.conductor = conductor

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
    def create_intent(data: dict[str, Any]) -> dict:
        return conductor.create_intent(data)

    @app.get("/intents/{intent_id}")
    def intent(intent_id: str) -> dict:
        return conductor.state()["intents"][intent_id]

    @app.post("/intents/{intent_id}/transition")
    def transition_intent(intent_id: str, data: Transition) -> dict:
        return conductor.transition_intent(intent_id, data.status)

    @app.get("/decisions")
    def decisions() -> list[dict]:
        return list(conductor.state()["decisions"].values())

    @app.post("/decisions", status_code=201)
    def create_decision(data: dict[str, Any]) -> dict:
        return conductor.log_decision(data)

    @app.get("/decisions/{decision_id}")
    def decision(decision_id: str) -> dict:
        return conductor.state()["decisions"][decision_id]

    @app.post("/decisions/{decision_id}/transition")
    def transition_decision(decision_id: str, data: Transition) -> dict:
        return conductor.transition_decision(decision_id, data.status)

    @app.get("/tasks")
    def tasks(member_id: str | None = None) -> dict:
        if member_id is not None:
            return conductor.get_my_task(member_id)
        return {"tasks": list(conductor.state()["tasks"].values())}

    @app.post("/tasks", status_code=201)
    def dispatch_task(data: Dispatch) -> dict:
        return conductor.dispatch_task(
            data.intent_id, data.member_id, data.spec, data.forbidden_paths
        )

    @app.get("/tasks/{task_id}")
    def task(task_id: str) -> dict:
        return conductor.state()["tasks"][task_id]

    @app.post("/tasks/{task_id}/start")
    def start_task(task_id: str, data: Member) -> dict:
        return conductor.start_task(task_id, data.member_id)

    @app.post("/artifacts", status_code=201)
    def submit_artifact(data: Submission) -> dict:
        return conductor.submit_artifact(data.member_id, data.artifact)

    @app.post("/tasks/{task_id}/submit")
    def submit_task(task_id: str, data: Submission) -> dict:
        assigned = conductor.state()["tasks"][task_id]
        if assigned["member_id"] != data.member_id:
            raise PermissionError("Task belongs to another member")
        artifact = dict(data.artifact)
        if artifact.get("intent_id", assigned["intent_id"]) != assigned["intent_id"]:
            raise ValueError("artifact.intent_id must match the task in the request path")
        artifact["intent_id"] = assigned["intent_id"]
        return conductor.submit_artifact(data.member_id, artifact)

    @app.post("/tasks/{task_id}/merge")
    def merge_task(task_id: str, data: Approval) -> dict:
        """Record human approval after performing the actual Git merge externally."""
        return conductor.merge_task(task_id, data.author)

    @app.get("/conflicts")
    def conflicts() -> list[dict]:
        return list(conductor.state()["conflicts"].values())

    @app.post("/conflicts/check")
    def detect_conflicts() -> dict:
        return conductor.detect_conflicts()

    @app.post("/conflicts/{conflict_id}/resolve")
    def resolve_conflict(conflict_id: str, data: Resolution) -> dict:
        return conductor.resolve_conflict(conflict_id, data.author, data.action, data.rationale)

    @app.get("/sync")
    def check_sync(member_id: str | None = None, since_version: str | None = None) -> dict:
        return conductor.check_backbone_sync(member_id, since_version)

    @app.post("/sync")
    def sync(data: Sync) -> dict:
        return conductor.sync(data.remote, data.branch)

    @app.get("/timeline")
    def timeline(limit: int = Query(default=50, ge=1, le=1000)) -> list[dict]:
        return conductor.log(limit)

    return app
