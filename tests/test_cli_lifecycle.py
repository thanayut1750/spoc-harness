import json
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from org_harness import cli
from org_harness.config import Settings

runner = CliRunner()


@pytest.mark.parametrize(
    "host,expected",
    [
        ("0.0.0.0", "http://127.0.0.1:8123"),
        ("::", "http://[::1]:8123"),
        ("::1", "http://[::1]:8123"),
        ("localhost", "http://localhost:8123"),
    ],
)
def test_cli_api_requests_format_ipv6_and_map_wildcards_to_loopback(monkeypatch, host, expected):
    settings = Settings(_env_file=None, api_host=host, api_port=8123)
    assert cli.api_base_url(settings) == expected
    requested = []

    def capture(method, url, **kwargs):
        requested.append(url)
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request(method, url))

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(httpx, "request", capture)
    assert cli.request("GET", "/api/runs") == {"status": "ok"}
    assert requested == [f"{expected}/api/runs"]


@pytest.fixture
def lifecycle_commands(monkeypatch, tmp_path):
    from org_harness import lifecycle

    settings = Settings(_env_file=None, data_dir=tmp_path)
    calls = []

    def invoke(action, **options):
        calls.append((action, options))
        return {"action": action, "services": {"api": "running", "worker": "running"}}

    manager = SimpleNamespace(
        start=lambda **options: invoke("start", **options),
        stop=lambda **options: invoke("stop", **options),
        restart=lambda **options: invoke("restart", **options),
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(lifecycle, "ServiceManager", lambda configured: manager)
    return manager, calls


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_lifecycle_commands_forward_options_and_display_service_summary(lifecycle_commands, action):
    _, calls = lifecycle_commands
    arguments = [action, "--timeout", "30"]
    if action != "start":
        arguments.append("--force")
    result = runner.invoke(cli.app, arguments)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["action"] == action
    assert calls == [(action, {"timeout": 30.0, **({"force": True} if action != "start" else {})})]


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_lifecycle_invalid_timeout_never_invokes_manager(lifecycle_commands, action):
    _, calls = lifecycle_commands
    result = runner.invoke(cli.app, [action, "--timeout", "0"])
    assert result.exit_code == 2
    assert calls == []


def test_lifecycle_errors_have_actionable_output_without_traceback(lifecycle_commands, monkeypatch):
    from org_harness.lifecycle import LifecycleError

    manager, _ = lifecycle_commands

    def reject(**options):
        raise LifecycleError("API port is already in use by an unverified process")

    monkeypatch.setattr(manager, "start", reject)
    result = runner.invoke(cli.app, ["start"])
    assert result.exit_code == 1
    assert "Cannot start services:" in result.output
    assert "unverified process" in result.output
    assert "Traceback" not in result.output


def test_invalid_service_settings_do_not_echo_private_values(monkeypatch):
    def invalid_settings():
        raise ValueError("private-provider-key")

    monkeypatch.setattr(cli, "Settings", invalid_settings)
    result = runner.invoke(cli.app, ["start"])
    assert result.exit_code == 1
    assert "check .env" in result.output
    assert "private-provider-key" not in result.output


def test_lifecycle_io_error_is_readable_without_raw_exception_content(
    lifecycle_commands,
    monkeypatch,
):
    manager, _ = lifecycle_commands

    def denied(**options):
        raise PermissionError("private internal path")

    monkeypatch.setattr(manager, "stop", denied)
    result = runner.invoke(cli.app, ["stop"])
    assert result.exit_code == 1
    assert "PermissionError" in result.output
    assert "private internal path" not in result.output


def test_help_lists_lifecycle_commands_without_starting_services():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for action in ("start", "stop", "restart"):
        assert action in result.output
