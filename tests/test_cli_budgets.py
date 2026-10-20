"""CLI submissions inherit workspace budgets through the same API as the office."""

import httpx
import pytest
from typer.testing import CliRunner

from org_harness import cli
from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.storage import MemoryStorage


def test_cli_autonomous_explicitly_removes_all_three_caps(monkeypatch):
    submitted = []
    monkeypatch.setattr(
        cli, "request", lambda method, path, *, body: submitted.append(body) or {"status": "queued"}
    )
    result = CliRunner().invoke(
        cli.app, ["run", "Complete a week-long investigation", "--autonomous"]
    )
    assert result.exit_code == 0, result.output
    assert submitted == [
        {
            "user_request": "Complete a week-long investigation",
            "limits": {
                "max_model_calls": None,
                "worker_model_calls": None,
                "max_tool_calls": None,
            },
        }
    ]


@pytest.mark.parametrize(
    "saved",
    [
        {"max_model_calls": 500, "worker_model_calls": 17},
        {"max_model_calls": None, "worker_model_calls": 17},
        {"max_model_calls": 500, "worker_model_calls": None},
        {"max_model_calls": None, "worker_model_calls": None},
        {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None},
        {"max_model_calls": 500, "worker_model_calls": 17, "max_tool_calls": 900},
    ],
)
async def test_cli_submission_uses_saved_budgets_without_baking_in_schema_defaults(
    tmp_path, monkeypatch, saved
):
    submitted = []

    def capture(method, path, *, body):
        submitted.append((method, path, body))
        return {"run_id": "queued-via-api", "status": "queued"}

    monkeypatch.setattr(cli, "request", capture)
    storage = MemoryStorage()
    settings = Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, storage)), base_url="http://test"
    ) as client:
        assert (await client.put("/api/settings/budgets", json=saved)).status_code == 200
        result = CliRunner().invoke(
            cli.app, ["run", "Use the workspace call budget", "--workspace", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        method, path, body = submitted.pop()
        assert (method, path) == ("POST", "/api/runs")
        response = await client.request(method, path, json=body)
        assert response.status_code == 202
        run = await storage.get_run(response.json()["run_id"])
        assert {key: run["limits"][key] for key in saved} == saved
        assert run["limits"]["worker_timeout"] == 3600
        assert run["workspace_path"] == str(tmp_path.resolve())

        assert (
            await client.put(
                "/api/settings/budgets", json={"max_model_calls": 800, "worker_model_calls": 21}
            )
        ).status_code == 200
        original = await storage.get_run(run["run_id"])
        assert original["limits"] == run["limits"]
