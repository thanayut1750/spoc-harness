"""Application persistence. Production state lives in Postgres, never process memory."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

TERMINAL = {"succeeded", "failed", "cancelled"}


class NotFoundError(LookupError):
    pass


class ConflictError(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def new_run(payload: dict) -> dict:
    return {
        **payload,
        "run_id": str(uuid4()),
        "status": "queued",
        "created_at": timestamp(),
        "updated_at": timestamp(),
        "objectives": [],
        "progress": {},
        "outcomes": {},
        "review": None,
        "report": None,
        "pause_requested": False,
        "cancel_requested": False,
        "resume_decision": None,
        "model_calls": 0,
        "tool_calls": 0,
    }


def apply_command(run: dict, kind: str, payload: dict) -> dict:
    """Validate lifecycle changes in one place for memory and SQL transactions."""
    status = run["status"]
    if status in TERMINAL:
        raise ConflictError(f"Run is already {status}")
    if kind == "pause":
        if status not in {"queued", "running"}:
            raise ConflictError("Only queued or running runs can pause")
        run["pause_requested"] = True
        if status == "queued":
            run["status"] = "paused"
    elif kind == "cancel":
        run["cancel_requested"] = True
        run["status"] = "cancelled"
    elif kind == "resume":
        if status not in {"paused", "review"}:
            raise ConflictError("Run is not waiting for a decision")
        review = run.get("review")
        if review and payload.get("interrupt_id") != review.get("interrupt_id"):
            raise ConflictError("Decision does not match the current interrupt")
        action = payload.get("action", "continue")
        if action not in {"continue", "provide_context", "revise_kr", "retry_operation", "abort"}:
            raise ConflictError("Unknown review action")
        if (
            review
            and review.get("kind") in {"uncertain_operation", "unknown_operation"}
            and action not in {"retry_operation", "abort"}
        ):
            raise ConflictError("Choose retry_operation or abort for an uncertain command")
        if action == "provide_context" and not payload.get("context"):
            raise ConflictError("Context is required")
        if action == "revise_kr" and not (
            payload.get("kr_id")
            and (payload.get("description") or payload.get("acceptance_criteria"))
        ):
            raise ConflictError(
                "A revised KR needs its ID and a description or acceptance criteria"
            )
        run.update(pause_requested=False, status="queued", resume_decision=payload)
        if action == "abort":
            run.update(status="cancelled", cancel_requested=True)
    elif kind == "notes":
        if not payload.get("content", "").strip():
            raise ConflictError("A note cannot be empty")
    else:
        raise ConflictError("Unknown command")
    run["updated_at"] = timestamp()
    return run


class MemoryStorage:
    """Deterministic offline/test backend; explicitly opt in before using it."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.worker_guard = asyncio.Lock()
        self.runs: dict[str, dict] = {}
        self.events: list[dict] = []
        self.projection: dict[str, dict] = {}
        self.event_ids: dict[tuple[str, str], dict] = {}
        self.commands: dict[str, tuple[str, dict]] = {}
        self.notes: list[dict] = []
        self.artifacts: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}

    @asynccontextmanager
    async def worker_lock(self):
        if self.worker_guard.locked():
            yield None
            return
        async with self.worker_guard:
            yield True

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def ready(self) -> bool:
        return True

    def _cached(self, key: str | None, value: Any) -> dict | None:
        if key and key in self.commands:
            digest, result = self.commands[key]
            if digest != fingerprint(value):
                raise ConflictError("Idempotency key was already used with a different request")
            return copy.deepcopy(result)
        return None

    def _save(self, key: str | None, value: Any, result: dict) -> None:
        if key:
            self.commands[key] = (fingerprint(value), copy.deepcopy(result))

    async def create_run(self, payload: dict, idempotency_key: str | None = None) -> dict:
        async with self.lock:
            value = {"create_run": payload}
            cached = self._cached(idempotency_key, value)
            if cached:
                return cached
            run = new_run(copy.deepcopy(payload))
            self.runs[run["run_id"]] = run
            self.jobs[run["run_id"]] = {"owner": None, "lease_until": 0.0}
            self._save(idempotency_key, value, run)
            return copy.deepcopy(run)

    async def get_run(self, run_id: str) -> dict:
        async with self.lock:
            if run_id not in self.runs:
                raise NotFoundError("Run not found")
            return copy.deepcopy(self.runs[run_id])

    async def list_runs(self) -> list[dict]:
        async with self.lock:
            return copy.deepcopy(
                sorted(self.runs.values(), key=lambda r: r["created_at"], reverse=True)
            )

    async def update_run(self, run_id: str, **fields: Any) -> dict:
        async with self.lock:
            if run_id not in self.runs:
                raise NotFoundError("Run not found")
            # A finishing graph cannot resurrect a cancelled run.
            if self.runs[run_id]["status"] == "cancelled":
                fields.pop("status", None)
            self.runs[run_id].update(copy.deepcopy(fields), updated_at=timestamp())
            return copy.deepcopy(self.runs[run_id])

    async def replay_command(
        self, run_id: str, kind: str, payload: dict, idempotency_key: str | None = None
    ) -> dict | None:
        async with self.lock:
            return self._cached(
                idempotency_key, {"run_id": run_id, "kind": kind, "payload": payload}
            )

    async def command(
        self, run_id: str, kind: str, payload: dict, idempotency_key: str | None = None
    ) -> dict:
        async with self.lock:
            value = {"run_id": run_id, "kind": kind, "payload": payload}
            cached = self._cached(idempotency_key, value)
            if cached:
                return cached
            if run_id not in self.runs:
                raise NotFoundError("Run not found")
            run = apply_command(copy.deepcopy(self.runs[run_id]), kind, payload)
            self.runs[run_id] = run
            if kind == "notes":
                self.notes.append(
                    {
                        **payload,
                        "run_id": run_id,
                        "note_id": str(uuid4()),
                        "created_at": timestamp(),
                        "consumed": False,
                    }
                )
            if kind == "resume":
                self.jobs[run_id] = {"owner": None, "lease_until": 0.0}
                if payload.get("action") == "retry_operation":
                    operation_id = (run.get("review") or {}).get("operation_id")
                    if operation_id in self.operations:
                        self.operations[operation_id]["status"] = "retry_approved"
            result = {"run_id": run_id, "status": run["status"]}
            self._save(idempotency_key, value, result)
            return result

    async def consume_notes(self, run_id: str, agent_id: str) -> list[dict]:
        async with self.lock:
            selected = []
            for note in self.notes:
                if (
                    note["run_id"] == run_id
                    and not note["consumed"]
                    and note.get("agent_id") in (None, agent_id)
                ):
                    note["consumed"] = True
                    selected.append(copy.deepcopy(note))
            return selected

    async def emit(self, event: dict) -> dict:
        async with self.lock:
            event = copy.deepcopy(event)
            event.setdefault("schema_version", 1)
            event.setdefault("source", "harness")
            event.setdefault("event_id", str(uuid4()))
            key = (event["source"], event["event_id"])
            if key in self.event_ids:
                return copy.deepcopy(self.event_ids[key])
            event.update(seq=len(self.events) + 1)
            event.setdefault("timestamp", timestamp())
            event.setdefault("data", {})
            event.setdefault("summary", "")
            self.events.append(event)
            self.event_ids[key] = event
            projection_key = f"{event['source']}:{event['agent_id']}"
            self.projection[projection_key] = event
            return copy.deepcopy(event)

    async def events_after(
        self, cursor: int = 0, run_id: str | None = None, limit: int = 500
    ) -> list[dict]:
        async with self.lock:
            return copy.deepcopy(
                [
                    event
                    for event in self.events
                    if event["seq"] > cursor and (not run_id or event.get("run_id") == run_id)
                ][:limit]
            )

    async def office_snapshot(self) -> dict:
        async with self.lock:
            return {
                "agents": copy.deepcopy(list(self.projection.values())),
                "cursor": len(self.events),
            }

    async def register_artifact(self, metadata: dict) -> dict:
        async with self.lock:
            item = copy.deepcopy(metadata)
            artifact_id = item.get("artifact_id", str(uuid4()))
            item.update(artifact_id=artifact_id)
            item.setdefault(
                "created_at", self.artifacts.get(artifact_id, {}).get("created_at", timestamp())
            )
            if artifact_id in self.artifacts:
                if self.artifacts[artifact_id] != item:
                    raise ConflictError("Artifact ID already registered")
            self.artifacts[artifact_id] = item
            return copy.deepcopy(item)

    async def list_artifacts(self, run_id: str) -> list[dict]:
        async with self.lock:
            return copy.deepcopy([v for v in self.artifacts.values() if v["run_id"] == run_id])

    async def get_artifact(self, artifact_id: str) -> dict:
        async with self.lock:
            if artifact_id not in self.artifacts:
                raise NotFoundError("Artifact not found")
            return copy.deepcopy(self.artifacts[artifact_id])

    async def reserve_budget(self, run_id: str, kind: str, amount: int = 1) -> int:
        if kind not in {"model", "tool"} or amount < 1:
            raise ValueError("Invalid budget reservation")
        async with self.lock:
            run = self.runs[run_id]
            field = f"{kind}_calls"
            limit = run.get("limits", {}).get(f"max_{kind}_calls", 100 if kind == "model" else 200)
            if run[field] + amount > limit:
                raise BudgetExceeded(f"Run {kind} call budget exhausted")
            run[field] += amount
            return run[field]

    async def begin_operation(
        self, run_id: str, operation_id: str, kind: str, request: dict
    ) -> dict:
        async with self.lock:
            existing = self.operations.get(operation_id)
            if existing and fingerprint(existing["request"]) != fingerprint(request):
                raise ConflictError("Operation ID collision")
            if existing and existing["status"] != "retry_approved":
                return copy.deepcopy(existing)
            self.operations[operation_id] = {
                "operation_id": operation_id,
                "run_id": run_id,
                "kind": kind,
                "request": copy.deepcopy(request),
                "status": "pending",
                "result": None,
                "created_at": timestamp(),
            }
            return copy.deepcopy(self.operations[operation_id])

    async def complete_operation(
        self, operation_id: str, result: Any, status: str = "done"
    ) -> None:
        async with self.lock:
            self.operations[operation_id].update(status=status, result=copy.deepcopy(result))

    async def get_operation(self, operation_id: str) -> dict | None:
        async with self.lock:
            return copy.deepcopy(self.operations.get(operation_id))

    async def uncertain_operations(self, run_id: str) -> list[dict]:
        async with self.lock:
            return copy.deepcopy(
                [
                    v
                    for v in self.operations.values()
                    if v["run_id"] == run_id and v["kind"] == "command" and v["status"] == "pending"
                ]
            )

    async def claim_job(self, worker_id: str, lease_seconds: int = 30) -> dict | None:
        async with self.lock:
            now = time.monotonic()
            if any(v["owner"] and v["lease_until"] > now for v in self.jobs.values()):
                return None
            for run_id, job in self.jobs.items():
                run = self.runs[run_id]
                if run["status"] not in {"queued", "running"}:
                    continue
                recovered = run["status"] == "running"
                job.update(owner=worker_id, lease_until=now + lease_seconds)
                run.update(status="running", updated_at=timestamp())
                return {**copy.deepcopy(run), "recovered": recovered}
            return None

    async def heartbeat(self, run_id: str, worker_id: str, lease_seconds: int = 30) -> bool:
        async with self.lock:
            job = self.jobs.get(run_id)
            if not job or job["owner"] != worker_id:
                return False
            job["lease_until"] = time.monotonic() + lease_seconds
            return True

    async def finish_job(self, run_id: str, worker_id: str) -> None:
        async with self.lock:
            job = self.jobs.get(run_id)
            if job and job["owner"] == worker_id:
                job.update(owner=None, lease_until=0.0)


SCHEMA = """
CREATE TABLE IF NOT EXISTS harness_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS harness_runs (run_id text PRIMARY KEY, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS harness_jobs (run_id text PRIMARY KEY REFERENCES harness_runs(run_id), owner text, lease_until timestamptz);
CREATE TABLE IF NOT EXISTS harness_events (seq bigserial PRIMARY KEY, source text NOT NULL, event_id text NOT NULL, run_id text, data jsonb NOT NULL, UNIQUE(source,event_id));
CREATE TABLE IF NOT EXISTS harness_projection (agent_key text PRIMARY KEY, data jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS harness_commands (key text PRIMARY KEY, digest text NOT NULL, result jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS harness_notes (note_id text PRIMARY KEY, run_id text NOT NULL REFERENCES harness_runs(run_id), agent_id text, consumed boolean NOT NULL DEFAULT false, data jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS harness_artifacts (artifact_id text PRIMARY KEY, run_id text NOT NULL REFERENCES harness_runs(run_id), data jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS harness_operations (operation_id text PRIMARY KEY, run_id text NOT NULL REFERENCES harness_runs(run_id), data jsonb NOT NULL);
CREATE INDEX IF NOT EXISTS harness_events_run_seq ON harness_events(run_id,seq);
INSERT INTO harness_migrations(version) VALUES (1) ON CONFLICT DO NOTHING;
"""


class PostgresStorage:
    def __init__(self, database_url: str) -> None:
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        self.pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
            database_url,
            connection_class=cast(type[AsyncConnection[dict[str, Any]]], AsyncConnection),
            open=False,
            min_size=1,
            max_size=10,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        )

    @asynccontextmanager
    async def worker_lock(self):
        # Session lock spans execution; a slow heartbeat cannot start a second worker.
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute("SELECT pg_try_advisory_lock(73910404) AS acquired")
            ).fetchone()
            assert row is not None  # SELECT always returns one advisory-lock result.
            if not row["acquired"]:
                yield None
                return
            try:
                yield conn
            finally:
                await conn.execute("SELECT pg_advisory_unlock(73910404)")

    async def open(self) -> None:
        await self.pool.open(wait=True)

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self) -> None:
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(73910401)")
                await conn.execute(SCHEMA, prepare=False)

    async def ready(self) -> bool:
        try:
            async with self.pool.connection() as conn:
                row = await (
                    await conn.execute("SELECT version FROM harness_migrations WHERE version=1")
                ).fetchone()
                return bool(row)
        except Exception:
            return False

    @staticmethod
    def _json(value: Any):
        from psycopg.types.json import Jsonb

        return Jsonb(value)

    async def _cached(self, conn: Any, key: str | None, value: Any) -> dict | None:
        if not key:
            return None
        # Serialize all commands sharing this key, including the first insert.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        row = await (
            await conn.execute("SELECT digest,result FROM harness_commands WHERE key=%s", (key,))
        ).fetchone()
        if row:
            if row["digest"] != fingerprint(value):
                raise ConflictError("Idempotency key was already used with a different request")
            return row["result"]
        return None

    async def _save(self, conn: Any, key: str | None, value: Any, result: dict) -> None:
        if key:
            await conn.execute(
                "INSERT INTO harness_commands(key,digest,result) VALUES(%s,%s,%s)",
                (key, fingerprint(value), self._json(result)),
            )

    async def create_run(self, payload: dict, idempotency_key: str | None = None) -> dict:
        async with self.pool.connection() as conn, conn.transaction():
            value = {"create_run": payload}
            cached = await self._cached(conn, idempotency_key, value)
            if cached:
                return cached
            run = new_run(payload)
            await conn.execute(
                "INSERT INTO harness_runs(run_id,data) VALUES(%s,%s)",
                (run["run_id"], self._json(run)),
            )
            await conn.execute("INSERT INTO harness_jobs(run_id) VALUES(%s)", (run["run_id"],))
            await self._save(conn, idempotency_key, value, run)
            return run

    async def get_run(self, run_id: str) -> dict:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute("SELECT data FROM harness_runs WHERE run_id=%s", (run_id,))
            ).fetchone()
            if not row:
                raise NotFoundError("Run not found")
            return row["data"]

    async def list_runs(self) -> list[dict]:
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute("SELECT data FROM harness_runs ORDER BY created_at DESC")
            ).fetchall()
            return [row["data"] for row in rows]

    async def update_run(self, run_id: str, **fields: Any) -> dict:
        async with self.pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_runs WHERE run_id=%s FOR UPDATE", (run_id,)
                )
            ).fetchone()
            if not row:
                raise NotFoundError("Run not found")
            run = row["data"]
            if run["status"] == "cancelled":
                fields.pop("status", None)
            run.update(fields, updated_at=timestamp())
            await conn.execute(
                "UPDATE harness_runs SET data=%s WHERE run_id=%s", (self._json(run), run_id)
            )
            return run

    async def replay_command(
        self, run_id: str, kind: str, payload: dict, idempotency_key: str | None = None
    ) -> dict | None:
        async with self.pool.connection() as conn, conn.transaction():
            return await self._cached(
                conn, idempotency_key, {"run_id": run_id, "kind": kind, "payload": payload}
            )

    async def command(
        self, run_id: str, kind: str, payload: dict, idempotency_key: str | None = None
    ) -> dict:
        async with self.pool.connection() as conn, conn.transaction():
            value = {"run_id": run_id, "kind": kind, "payload": payload}
            cached = await self._cached(conn, idempotency_key, value)
            if cached:
                return cached
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_runs WHERE run_id=%s FOR UPDATE", (run_id,)
                )
            ).fetchone()
            if not row:
                raise NotFoundError("Run not found")
            run = apply_command(row["data"], kind, payload)
            await conn.execute(
                "UPDATE harness_runs SET data=%s WHERE run_id=%s", (self._json(run), run_id)
            )
            if kind == "notes":
                note = {
                    **payload,
                    "run_id": run_id,
                    "note_id": str(uuid4()),
                    "created_at": timestamp(),
                }
                await conn.execute(
                    "INSERT INTO harness_notes(note_id,run_id,agent_id,data) VALUES(%s,%s,%s,%s)",
                    (note["note_id"], run_id, payload.get("agent_id"), self._json(note)),
                )
            if kind == "resume":
                if payload.get("action") == "retry_operation":
                    op_id = (run.get("review") or {}).get("operation_id")
                    await conn.execute(
                        "UPDATE harness_operations SET data=jsonb_set(data,'{status}','\"retry_approved\"') WHERE operation_id=%s",
                        (op_id,),
                    )
                await conn.execute(
                    "UPDATE harness_jobs SET owner=NULL,lease_until=NULL WHERE run_id=%s", (run_id,)
                )
            result = {"run_id": run_id, "status": run["status"]}
            await self._save(conn, idempotency_key, value, result)
            return result

    async def consume_notes(self, run_id: str, agent_id: str) -> list[dict]:
        async with self.pool.connection() as conn, conn.transaction():
            rows = await (
                await conn.execute(
                    """UPDATE harness_notes SET consumed=true WHERE note_id IN
                (SELECT note_id FROM harness_notes WHERE run_id=%s AND NOT consumed AND
                (agent_id IS NULL OR agent_id=%s) FOR UPDATE SKIP LOCKED) RETURNING data""",
                    (run_id, agent_id),
                )
            ).fetchall()
            return [row["data"] for row in rows]

    async def emit(self, event: dict) -> dict:
        event = copy.deepcopy(event)
        event.setdefault("schema_version", 1)
        event.setdefault("source", "harness")
        event.setdefault("event_id", str(uuid4()))
        event.setdefault("timestamp", timestamp())
        event.setdefault("data", {})
        event.setdefault("summary", "")
        async with self.pool.connection() as conn, conn.transaction():
            # Event sequences must commit in cursor order; otherwise a snapshot can skip
            # a lower sequence that another transaction has not committed yet.
            await conn.execute("SELECT pg_advisory_xact_lock(73910402)")
            row = await (
                await conn.execute(
                    "SELECT seq,data FROM harness_events WHERE source=%s AND event_id=%s",
                    (event["source"], event["event_id"]),
                )
            ).fetchone()
            if row:
                return {"schema_version": 1, **row["data"], "seq": row["seq"]}
            row = await (
                await conn.execute(
                    "INSERT INTO harness_events(source,event_id,run_id,data) VALUES(%s,%s,%s,%s) RETURNING seq",
                    (event["source"], event["event_id"], event.get("run_id"), self._json(event)),
                )
            ).fetchone()
            assert row is not None  # INSERT RETURNING produced the new event.
            event["seq"] = row["seq"]
            await conn.execute(
                "INSERT INTO harness_projection(agent_key,data) VALUES(%s,%s) ON CONFLICT(agent_key) DO UPDATE SET data=excluded.data",
                (f"{event['source']}:{event['agent_id']}", self._json(event)),
            )
            return event

    async def events_after(
        self, cursor: int = 0, run_id: str | None = None, limit: int = 500
    ) -> list[dict]:
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT seq,data FROM harness_events WHERE seq>%s AND (%s::text IS NULL OR run_id=%s) ORDER BY seq LIMIT %s",
                    (cursor, run_id, run_id, limit),
                )
            ).fetchall()
            return [{"schema_version": 1, **row["data"], "seq": row["seq"]} for row in rows]

    async def office_snapshot(self) -> dict:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            rows = await (
                await conn.execute("SELECT data FROM harness_projection ORDER BY agent_key")
            ).fetchall()
            cursor = await (
                await conn.execute("SELECT COALESCE(MAX(seq),0) AS cursor FROM harness_events")
            ).fetchone()
            assert cursor is not None  # Aggregate SELECT returns a row even with no events.
            return {
                "agents": [{"schema_version": 1, **row["data"]} for row in rows],
                "cursor": cursor["cursor"],
            }

    async def register_artifact(self, metadata: dict) -> dict:
        item = copy.deepcopy(metadata)
        item.setdefault("artifact_id", str(uuid4()))
        item.setdefault("created_at", timestamp())
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO harness_artifacts(artifact_id,run_id,data) VALUES(%s,%s,%s) ON CONFLICT(artifact_id) DO NOTHING",
                (item["artifact_id"], item["run_id"], self._json(item)),
            )
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_artifacts WHERE artifact_id=%s",
                    (item["artifact_id"],),
                )
            ).fetchone()
            assert row is not None  # Insert or pre-existing unique artifact is visible.
            if "created_at" not in metadata:
                item["created_at"] = row["data"]["created_at"]
            if row["data"] != item:
                raise ConflictError("Artifact ID already registered")
            return row["data"]

    async def list_artifacts(self, run_id: str) -> list[dict]:
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT data FROM harness_artifacts WHERE run_id=%s ORDER BY data->>'created_at',artifact_id",
                    (run_id,),
                )
            ).fetchall()
            return [row["data"] for row in rows]

    async def get_artifact(self, artifact_id: str) -> dict:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_artifacts WHERE artifact_id=%s", (artifact_id,)
                )
            ).fetchone()
            if not row:
                raise NotFoundError("Artifact not found")
            return row["data"]

    async def reserve_budget(self, run_id: str, kind: str, amount: int = 1) -> int:
        if kind not in {"model", "tool"} or amount < 1:
            raise ValueError("Invalid budget reservation")
        async with self.pool.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_runs WHERE run_id=%s FOR UPDATE", (run_id,)
                )
            ).fetchone()
            if not row:
                raise NotFoundError("Run not found")
            run = row["data"]
            field = f"{kind}_calls"
            limit = run.get("limits", {}).get(f"max_{kind}_calls", 100 if kind == "model" else 200)
            if run[field] + amount > limit:
                raise BudgetExceeded(f"Run {kind} call budget exhausted")
            run[field] += amount
            await conn.execute(
                "UPDATE harness_runs SET data=%s WHERE run_id=%s", (self._json(run), run_id)
            )
            return run[field]

    async def begin_operation(
        self, run_id: str, operation_id: str, kind: str, request: dict
    ) -> dict:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (operation_id,)
            )
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_operations WHERE operation_id=%s FOR UPDATE",
                    (operation_id,),
                )
            ).fetchone()
            if row:
                existing = row["data"]
                if fingerprint(existing["request"]) != fingerprint(request):
                    raise ConflictError("Operation ID collision")
                if existing["status"] != "retry_approved":
                    return existing
            item = {
                "operation_id": operation_id,
                "run_id": run_id,
                "kind": kind,
                "request": request,
                "status": "pending",
                "result": None,
                "created_at": timestamp(),
            }
            await conn.execute(
                "INSERT INTO harness_operations(operation_id,run_id,data) VALUES(%s,%s,%s) ON CONFLICT(operation_id) DO UPDATE SET data=excluded.data",
                (operation_id, run_id, self._json(item)),
            )
            return item

    async def complete_operation(
        self, operation_id: str, result: Any, status: str = "done"
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE harness_operations SET data=data || %s WHERE operation_id=%s",
                (self._json({"result": result, "status": status}), operation_id),
            )

    async def get_operation(self, operation_id: str) -> dict | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT data FROM harness_operations WHERE operation_id=%s", (operation_id,)
                )
            ).fetchone()
            return row["data"] if row else None

    async def uncertain_operations(self, run_id: str) -> list[dict]:
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT data FROM harness_operations WHERE run_id=%s AND data->>'kind'='command' AND data->>'status'='pending'",
                    (run_id,),
                )
            ).fetchall()
            return [row["data"] for row in rows]

    async def claim_job(self, worker_id: str, lease_seconds: int = 30) -> dict | None:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(73910403)")
            active = await (
                await conn.execute(
                    "SELECT run_id FROM harness_jobs WHERE owner IS NOT NULL AND lease_until>now() LIMIT 1"
                )
            ).fetchone()
            if active:
                return None
            row = await (
                await conn.execute("""SELECT r.run_id,r.data FROM harness_jobs j JOIN harness_runs r USING(run_id)
                WHERE r.data->>'status' IN ('queued','running') AND (j.lease_until IS NULL OR j.lease_until<now())
                ORDER BY r.created_at LIMIT 1 FOR UPDATE OF j,r SKIP LOCKED""")
            ).fetchone()
            if not row:
                return None
            run = row["data"]
            recovered = run["status"] == "running"
            run.update(status="running", updated_at=timestamp())
            await conn.execute(
                "UPDATE harness_jobs SET owner=%s,lease_until=now()+(%s*interval '1 second') WHERE run_id=%s",
                (worker_id, lease_seconds, row["run_id"]),
            )
            await conn.execute(
                "UPDATE harness_runs SET data=%s WHERE run_id=%s", (self._json(run), row["run_id"])
            )
            return {**run, "recovered": recovered}

    async def heartbeat(self, run_id: str, worker_id: str, lease_seconds: int = 30) -> bool:
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                "UPDATE harness_jobs SET lease_until=now()+(%s*interval '1 second') WHERE run_id=%s AND owner=%s AND lease_until>now()",
                (lease_seconds, run_id, worker_id),
            )
            return cursor.rowcount == 1

    async def finish_job(self, run_id: str, worker_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE harness_jobs SET owner=NULL,lease_until=NULL WHERE run_id=%s AND owner=%s",
                (run_id, worker_id),
            )


def create_storage(settings: Any):
    if getattr(settings, "storage_backend", "postgres") == "memory":
        return MemoryStorage()
    if not getattr(settings, "database_url", None):
        raise ValueError("DATABASE_URL is required; memory storage requires STORAGE_BACKEND=memory")
    database_url = settings.database_url
    if hasattr(database_url, "get_secret_value"):
        database_url = database_url.get_secret_value()
    return PostgresStorage(database_url)
