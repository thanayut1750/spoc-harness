"""Loopback HTTP API and durable activity stream for the office client."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from org_harness.config import Settings, configure_tracing
from org_harness.models import (
    ActivityEvent,
    ConfigurableAgent,
    Contract,
    Deliverable,
    ModelSelection,
    ReviewDecision,
    RunCreate,
)
from org_harness.storage import ConflictError, MemoryStorage, NotFoundError, create_storage
from org_harness.text_safety import contains_invalid_json_text


class NoteCreate(Contract):
    agent_id: str | None = Field(default=None, max_length=100)
    content: str = Field(min_length=1, max_length=20000)


class RegenesisRequest(Contract):
    confirmation: str


def public_run(run: dict) -> dict:
    """Hide stale approvals while a new KR version or execution epoch runs."""
    versions = {
        kr["kr_id"]: kr.get("version", 1)
        for objective in run.get("objectives", [])
        for kr in objective.get("key_results", [])
    }
    if run.get("epochs"):
        run["outcomes"] = {
            kr_id: outcome
            for kr_id, outcome in run.get("outcomes", {}).items()
            if outcome.get("epoch", 0) == run["epochs"].get(kr_id, 0)
            and outcome.get("version", 1) == versions.get(kr_id, 1)
        }
    return run


async def reviewed_run_view(storage: Any, run: dict) -> dict:
    """Derive a review packet from recorded evidence without rewriting its interrupt."""
    if not run.get("review"):
        return public_run(run)
    from org_harness.runtime import enrich_review_context

    artifacts: list[dict] = []
    for item in await storage.list_artifacts(run["run_id"]):
        metadata = {key: value for key, value in item.items() if key != "path"}
        if item.get("kind") == "deliverable" and item.get("path"):
            # Legacy outcomes did not retain the worker deliverable on rejection.
            # Read only the bounded, registered summary record, never source/log bodies.
            try:
                with Path(item["path"]).open("rb") as handle:
                    body = handle.read(65537)
                digest = item.get("sha256")
                intact = not digest or hashlib.sha256(body).hexdigest() == digest
                if len(body) <= 65536 and intact:
                    metadata["deliverable"] = Deliverable.model_validate_json(body).model_dump(
                        mode="json"
                    )
            except (OSError, ValueError):
                pass
        artifacts.append(metadata)

    events: list[dict] = []
    cursor = 0
    history_truncated = False
    for _ in range(20):
        batch = await storage.events_after(cursor, run["run_id"], limit=500)
        if not batch:
            break
        cursor = batch[-1]["seq"]
        events.extend(event for event in batch if event.get("source", "harness") == "harness")
        if len(batch) < 500:
            break
    else:
        history_truncated = True
    original = dict(run["review"])
    enriched = enrich_review_context(original, run, artifacts=artifacts, events=events)
    context = enriched.get("context", {})
    if history_truncated:
        context = {**context, "truncated": True}
    # Original action policy and checkpoint interrupt identity remain authoritative.
    run["review"] = {**original, "context": context}
    return public_run(run)


def create_app(settings: Settings | None = None, storage: Any = None) -> FastAPI:
    settings = settings or Settings()
    configure_tracing(settings)
    storage = storage or create_storage(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await storage.open()
        yield
        await storage.close()

    app = FastAPI(title="SPOC Harness", version="0.1.0", lifespan=lifespan)
    app.state.storage = storage
    app.state.settings = settings
    mutations = asyncio.Lock()
    app.state.reset_generation = 0

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        # Raw inputs/ctx can echo private data or contain a surrogate that the
        # response itself cannot encode. Public diagnostics need only the field
        # location and validation category.
        detail = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(NotFoundError)
    async def missing(_: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(_: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if contains_invalid_json_text(
            [
                request.scope.get("path", ""),
                list(request.query_params.multi_items()),
                list(request.headers.items()),
            ]
        ):
            return JSONResponse(
                status_code=422, content={"detail": "Request contains unsupported Unicode text"}
            )
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin != f"{request.url.scheme}://{request.headers.get('host')}"
        ):
            return JSONResponse(status_code=403, content={"detail": "Use the same-origin API"})
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            async with mutations:
                return await call_next(request)
        return await call_next(request)

    async def activity(run_id: str, kind: str, key: str | None = None) -> None:
        identifier = hashlib.sha256(key.encode()).hexdigest() if key else None
        event = {
            "agent_id": "executive",
            "run_id": run_id,
            "activity": "waiting",
            "summary": f"Run {kind}",
            "data": {"command": kind},
        }
        if identifier:
            event["event_id"] = f"command:{identifier}"
        await storage.emit(event)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready():
        if not await storage.ready():
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unavailable",
                    "detail": "Database needs connection or migration",
                },
            )
        return {
            "status": "ready",
            "mode": "demo" if settings.harness_test_mode else "live",
            "storage": "memory" if isinstance(storage, MemoryStorage) else "postgres",
        }

    @app.post("/api/runs", status_code=202)
    async def submit(body: RunCreate, idempotency_key: str | None = Header(default=None)):
        payload = body.model_dump(mode="json", by_alias=True, exclude_none=True)
        request_payload = dict(payload)
        selected = body.model_config_selection
        if selected is None:
            saved = await storage.get_setting("model_config")
            selected = (
                ModelSelection.model_validate(saved)
                if saved
                else settings.default_model_selection()
            )
        try:
            settings.validate_model_selection(selected)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        payload["model_config"] = selected.model_dump(mode="json")
        agent_models = body.agent_model_configs
        if agent_models is None:
            agent_models = {
                name: ModelSelection.model_validate(value)
                for name, value in (await storage.get_setting("agent_model_configs") or {}).items()
            }
        try:
            for selection in agent_models.values():
                settings.validate_model_selection(selection)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        payload["agent_model_configs"] = {
            name: value.model_dump(mode="json") for name, value in agent_models.items()
        }
        if body.workspace_path:
            try:
                workspace = Path(body.workspace_path).expanduser().resolve()
                exists = workspace.is_dir()
            except (OSError, ValueError, RuntimeError) as exc:
                raise HTTPException(
                    422, "Workspace path must resolve to an existing directory"
                ) from exc
            if not exists:
                raise HTTPException(422, "Workspace must be an existing directory")
            payload["workspace_path"] = str(workspace)
        run = await storage.create_run(payload, idempotency_key, request_payload=request_payload)
        await storage.emit(
            {
                "event_id": f"run:{run['run_id']}:created",
                "source": "harness",
                "agent_id": "executive",
                "run_id": run["run_id"],
                "activity": "waiting",
                "summary": "Objective queued",
                "data": {},
            }
        )
        return {"run_id": run["run_id"], "status": run["status"]}

    @app.get("/api/settings")
    async def get_settings():
        return settings.public_settings(
            await storage.get_setting("model_config"),
            await storage.get_setting("agent_model_configs"),
        )

    @app.put("/api/settings/model")
    async def save_model(body: ModelSelection):
        try:
            settings.validate_model_selection(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        await storage.save_setting("model_config", body.model_dump(mode="json"))
        return await get_settings()

    @app.put("/api/settings/agents/{agent_id}")
    async def save_agent_model(agent_id: ConfigurableAgent, body: ModelSelection):
        try:
            settings.validate_model_selection(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        selections = await storage.get_setting("agent_model_configs") or {}
        selections[agent_id] = body.model_dump(mode="json")
        await storage.save_setting("agent_model_configs", selections)
        return await get_settings()

    @app.delete("/api/settings/agents/{agent_id}")
    async def inherit_agent_model(agent_id: ConfigurableAgent):
        selections = await storage.get_setting("agent_model_configs") or {}
        selections.pop(agent_id, None)
        if selections:
            await storage.save_setting("agent_model_configs", selections)
        else:
            await storage.delete_setting("agent_model_configs")
        return await get_settings()

    @app.post("/api/regenesis")
    async def reset(body: RegenesisRequest):
        if body.confirmation != "REGENESIS":
            raise HTTPException(422, "Type REGENESIS to confirm erasing harness data")
        from org_harness.reset import regenesis

        result = await regenesis(settings, storage)
        app.state.reset_generation += 1
        return result

    @app.get("/api/runs")
    async def runs():
        return [await reviewed_run_view(storage, run) for run in await storage.list_runs()]

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str):
        return await reviewed_run_view(storage, await storage.get_run(run_id))

    @app.post("/api/runs/{run_id}/pause")
    async def pause(run_id: str, idempotency_key: str | None = Header(default=None)):
        result = await storage.command(run_id, "pause", {}, idempotency_key)
        await activity(run_id, "pause requested", idempotency_key)
        return result

    @app.post("/api/runs/{run_id}/retry", status_code=202)
    async def retry(run_id: str, idempotency_key: str | None = Header(default=None)):
        result = await storage.command(run_id, "retry", {}, idempotency_key)
        await activity(run_id, "recovery queued", idempotency_key)
        return result

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str, idempotency_key: str | None = Header(default=None)):
        result = await storage.command(run_id, "cancel", {}, idempotency_key)
        await activity(run_id, "cancelled", idempotency_key)
        return result

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    async def resume(
        run_id: str, body: ReviewDecision, idempotency_key: str | None = Header(default=None)
    ):
        payload = body.model_dump(mode="json", exclude_none=True)
        replay = await storage.replay_command(run_id, "resume", payload, idempotency_key)
        if replay:
            return replay
        run = await storage.get_run(run_id)
        if run.get("review") and run["status"] in {"review", "paused"}:
            from org_harness.runtime import validate_review_decision

            try:
                validate_review_decision(run["review"], payload, run.get("objectives", []))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        result = await storage.command(run_id, "resume", payload, idempotency_key)
        await activity(run_id, "resumed", idempotency_key)
        return result

    @app.post("/api/runs/{run_id}/notes", status_code=202)
    async def note(
        run_id: str, body: NoteCreate, idempotency_key: str | None = Header(default=None)
    ):
        result = await storage.command(
            run_id, "notes", body.model_dump(mode="json"), idempotency_key
        )
        await activity(run_id, "guidance queued", idempotency_key)
        return result

    @app.get("/api/office")
    async def office():
        return await storage.office_snapshot()

    @app.get("/api/events/history")
    async def event_history(
        before: int | None = Query(default=None, ge=1),
        run_id: str | None = Query(default=None, min_length=1),
        agent_id: str | None = Query(default=None, min_length=1, max_length=100),
        source: str | None = Query(default=None, min_length=1, max_length=100),
        limit: int = Query(default=100, ge=1, le=500),
        generation: str | None = Query(default=None, min_length=1, max_length=200),
    ):
        """Read durable newest-first history without changing the live office projection."""
        return await storage.event_history(
            before=before,
            run_id=run_id,
            agent_id=agent_id,
            source=source,
            limit=limit,
            generation=generation,
        )

    @app.get("/api/events")
    async def events(
        request: Request,
        after: int = Query(default=0, ge=0),
        run_id: str | None = None,
        last_event_id: str | None = Header(default=None),
        generation: str | None = None,
    ):
        cursor = after
        local_generation = app.state.reset_generation
        stream_generation = await storage.get_reset_generation()
        stale_generation = generation is not None and generation != stream_generation
        if last_event_id:
            try:
                cursor = max(cursor, int(last_event_id))
            except ValueError as exc:
                raise HTTPException(422, "Last-Event-ID must be a numeric cursor") from exc

        async def stream():
            nonlocal cursor
            idle = 0
            yield "retry: 1500\n\n"
            if stale_generation:
                yield "event: reset\ndata: {}\n\n"
                return
            while not await request.is_disconnected():
                if (
                    local_generation != app.state.reset_generation
                    or stream_generation != await storage.get_reset_generation()
                ):
                    yield "event: reset\ndata: {}\n\n"
                    return
                batch = await storage.events_after(cursor, run_id)
                if batch:
                    for event in batch:
                        cursor = event["seq"]
                        yield f"id: {cursor}\nevent: activity\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
                    idle = 0
                else:
                    idle += 1
                    if idle >= 30:
                        yield ": keepalive\n\n"
                        idle = 0
                    await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/integrations/events", status_code=202)
    async def integration_event(body: ActivityEvent):
        if body.source in {"harness", "internal"} or body.source.startswith("harness:"):
            raise HTTPException(422, "External events require an external source")
        # Namespace projections by source; external events never update run records.
        event = body.model_dump(mode="json", exclude_none=True)
        return await storage.emit(event)

    @app.get("/api/runs/{run_id}/artifacts")
    async def artifacts(run_id: str):
        await storage.get_run(run_id)
        return [
            {key: value for key, value in item.items() if key != "path"}
            for item in await storage.list_artifacts(run_id)
        ]

    @app.get("/api/artifacts/{artifact_id}")
    async def artifact(artifact_id: str):
        metadata = await storage.get_artifact(artifact_id)
        location = metadata.get("path")
        if not isinstance(location, (str, Path)) or not str(location):
            raise HTTPException(404, "Artifact content is unavailable")
        try:
            path = Path(location)
            exists = path.is_file()
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "Artifact content is unavailable") from exc
        if not exists:
            raise HTTPException(404, "Artifact content is unavailable")
        return FileResponse(
            path,
            media_type=metadata.get("media_type", "application/octet-stream"),
            filename=metadata.get("name", path.name),
        )

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.is_dir():
        assets = frontend / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def client(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "API endpoint not found")
            candidate = (frontend / path).resolve()
            if candidate.is_relative_to(frontend.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return {
                "application": "SPOC Harness",
                "detail": "Build frontend to view the office",
                "api": "/docs",
            }

    return app
