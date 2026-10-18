"""Predictable HTTP/CLI resource errors stay explicit and do not become tracebacks."""

import httpx
import pytest
import typer

from org_harness.api import create_app
from org_harness.cli import request
from org_harness.config import Settings
from org_harness.storage import (
    ArtifactNotFoundError,
    MemoryStorage,
    OperationNotFoundError,
    PostgresStorage,
    RunNotFoundError,
)


async def test_storage_distinguishes_missing_artifacts_from_missing_runs():
    storage = MemoryStorage()
    with pytest.raises(ArtifactNotFoundError) as artifact:
        await storage.get_artifact("unknown")
    with pytest.raises(RunNotFoundError) as run:
        await storage.get_run("unknown")
    assert artifact.value.resource == "artifact"
    assert run.value.resource == "run"
    with pytest.raises(OperationNotFoundError):
        await storage.complete_operation("unknown", {"success": True})


@pytest.mark.integration
async def test_postgres_never_reports_success_for_a_missing_operation(postgres_url):
    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        with pytest.raises(OperationNotFoundError):
            await storage.complete_operation("unknown", {"success": True})
        assert await storage.get_operation("unknown") is None
    finally:
        await storage.close()


async def test_api_resource_and_workspace_errors_are_controlled(tmp_path):
    storage = MemoryStorage()
    app = create_app(Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path), storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/artifacts/unknown")).status_code == 404
        assert (await client.get("/api/runs/unknown")).status_code == 404
        for path in ("\x00invalid", str(tmp_path / "missing")):
            response = await client.post(
                "/api/runs", json={"user_request": "test", "workspace_path": path}
            )
            assert response.status_code == 422
        assert await storage.list_runs() == []
        run = await storage.create_run({"user_request": "test"})
        for value in (None, {}, "\x00invalid", str(tmp_path / "deleted.txt")):
            artifact = await storage.register_artifact({"run_id": run["run_id"], "path": value})
            response = await client.get(f"/api/artifacts/{artifact['artifact_id']}")
            assert response.status_code == 404
            assert response.json()["detail"] == "Artifact content is unavailable"


@pytest.mark.parametrize("body", ["not json", "[]", '{"detail":"Artifact not found"}'])
def test_cli_handles_nonstandard_http_errors_without_traceback(monkeypatch, capsys, body):
    response = httpx.Response(404, request=httpx.Request("GET", "http://test/api"), content=body)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: response)
    with pytest.raises(typer.Exit):
        request("GET", "/api/artifacts/missing")
    assert "HTTP 404:" in capsys.readouterr().err


def test_cli_reports_invalid_success_payload(monkeypatch, capsys):
    response = httpx.Response(200, request=httpx.Request("GET", "http://test/api"), text="not JSON")
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: response)
    with pytest.raises(typer.Exit):
        request("GET", "/api/runs")
    assert "invalid JSON" in capsys.readouterr().err
