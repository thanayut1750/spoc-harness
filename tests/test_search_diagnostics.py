"""Operator diagnostics follow the same web provider and credentials as agents."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from org_harness import cli, providers
from org_harness.config import Settings
from org_harness.storage import MemoryStorage


@pytest.fixture
def diagnostic_model(monkeypatch):
    instances = []

    class Model:
        def __init__(self, **kwargs):
            self.turn = 0
            self.closed = False
            instances.append(self)

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, *args, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return AIMessage(content='{"ok":true}')
            if self.turn == 2:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "check_connection", "args": {}, "id": "diagnostic"}],
                )
            return AIMessage(content="Connection verified")

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(providers, "ZaiChatModel", Model)
    return instances


@pytest.mark.parametrize("search_fails", [False, True])
async def test_exa_diagnostics_skip_mcp_and_report_partial_failure(
    monkeypatch, diagnostic_model, search_fails
):
    import langchain.mcp

    from org_harness import web_search

    calls = []

    class Client:
        def __init__(self, settings):
            pass

        async def search(self, query):
            calls.append("search")
            if search_fails:
                raise web_search.ExaSearchError("Exa search is unavailable")
            return {"results": []}

        async def read(self, url):
            calls.append("reader")
            return {"results": [{"text": "JSON documentation"}]}

        async def close(self):
            calls.append("closed")

    def forbidden(*args, **kwargs):
        pytest.fail("Exa diagnostics must not initialize legacy MCP")

    monkeypatch.setattr(web_search, "ExaWebClient", Client)
    monkeypatch.setattr(langchain.mcp, "MCPAdapter", forbidden)
    result = await cli.live_diagnostics(Settings(_env_file=None, exa_api_key="private-fixture"))
    assert result["web_search_provider"] == "exa"
    assert result["web_search"] is (not search_fails)
    assert result["web_reader"] is True
    assert result["provider_json"] is True and result["provider_tool_roundtrip"] is True
    assert "search_mcp" not in result and "reader_mcp" not in result
    if search_fails:
        assert result["web_search_error"] == "ExaSearchError"
    assert calls == ["search", "reader", "closed"]
    assert diagnostic_model[0].closed
    assert "private-fixture" not in json.dumps(result)


@pytest.mark.parametrize(
    "dedicated_key,configured_zai", [(True, False), (False, True), (False, False)]
)
async def test_explicit_legacy_diagnostics_use_zai_credentials_only(
    monkeypatch, diagnostic_model, dedicated_key, configured_zai
):
    import langchain.mcp

    from org_harness import web_search

    connections = []

    class Adapter:
        def __init__(self, config):
            connections.extend(config["mcpServers"].items())
            self.kind = next(iter(config["mcpServers"]))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            return [SimpleNamespace(name=self.kind)]

    def forbidden(*args, **kwargs):
        pytest.fail("Explicit legacy selection must not initialize Exa")

    monkeypatch.setattr(langchain.mcp, "MCPAdapter", Adapter)
    monkeypatch.setattr(web_search, "ExaWebClient", forbidden)
    result = await cli.live_diagnostics(
        Settings(
            _env_file=None,
            web_search_provider="zai_mcp",
            exa_api_key="unused-exa-secret",
            zai_api_key="dedicated-zai-secret" if dedicated_key else "",
            openai_base_url="https://api.z.ai/v4"
            if configured_zai
            else "https://api.openai.com/v1",
            openai_api_key="configured-model-secret",
        )
    )
    configured = dedicated_key or configured_zai
    assert result["web_search_provider"] == "zai_mcp"
    assert result["web_search"] is result["search_mcp"] is configured
    assert result["web_reader"] is result["reader_mcp"] is configured
    if configured:
        expected = "dedicated-zai-secret" if dedicated_key else "configured-model-secret"
        assert {kind for kind, _ in connections} == {"search", "reader"}
        assert all(
            config["headers"]["Authorization"] == f"Bearer {expected}" for _, config in connections
        )
    else:
        assert not connections
        assert result["search_mcp_error"] == result["reader_mcp_error"] == "ValueError"
    assert diagnostic_model[0].closed
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("reader_ready", [True, False])
def test_doctor_exit_status_uses_provider_independent_web_checks(monkeypatch, reader_ready):
    from org_harness import storage

    settings = Settings(_env_file=None, storage_backend="memory")

    async def live(config):
        return {
            "provider_json": True,
            "provider_tool_roundtrip": True,
            "web_search_provider": "exa",
            "web_search": True,
            "web_reader": reader_ready,
        }

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(storage, "create_storage", lambda _: MemoryStorage())
    monkeypatch.setattr(cli, "live_diagnostics", live)
    result = CliRunner().invoke(cli.app, ["doctor", "--live"])
    assert result.exit_code == (0 if reader_ready else 1), result.output
    assert json.loads(result.stdout)["web_search_provider"] == "exa"
