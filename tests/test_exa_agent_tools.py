"""Exercise provider-selected web tools through the actual bounded LangChain agents."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from test_agent_services import assignment, services_with_provider, tool_call
from test_dynamic_services import PLANNING_TOOL_NAMES

from org_harness import agent_services
from org_harness.models import (
    Constitution,
    Deliverable,
    EngineeringSpecialistSpec,
    EscalationSignal,
    StrategicObjective,
    StrategicPlan,
    TacticalPlan,
    worker_agent_id,
)
from org_harness.web_search import ExaWebClient

REFERENCE_URL = "https://docs.example.org/reference"
QUERY = "Current reference evidence"


def extracted_deliverable(body):
    payload = json.loads(body["messages"][-1]["content"])
    return {
        "content": Deliverable(
            kr_id=payload["kr_id"],
            department=payload["department"],
            worker_role=payload["worker_role"],
            summary="Completed the requested report using the recorded reference evidence.",
        ).model_dump_json()
    }


def research_assignment(role):
    kr, work = assignment()
    return (
        kr.model_copy(update={"target_department": "research"}),
        work.model_copy(update={"role": role}),
    )


def configure_exa(services):
    services.settings.exa_api_key = SecretStr("fixture-exa-key")
    services.settings.web_search_provider = "auto"


def forbid_mcp(monkeypatch, services):
    async def forbidden(*args, **kwargs):
        pytest.fail("Exa-selected work must not discover or invoke an MCP connection")

    monkeypatch.setattr(services, "_mcp_tool", forbidden)
    monkeypatch.setattr(services, "_invoke_mcp", forbidden)


@asynccontextmanager
async def exa_transport(monkeypatch, *, status=200):
    requests = []
    clients = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append((request, payload))
        if status != 200:
            return httpx.Response(status, json={"error": "PRIVATE_EXA_ERROR_BODY"})
        assert request.url.host == "api.exa.ai"
        assert request.headers["x-api-key"] == "fixture-exa-key"
        assert request.method == "POST"
        if request.url.path == "/search":
            assert payload["query"] == QUERY
        else:
            assert request.url.path == "/contents"
            assert payload["urls"] == [REFERENCE_URL]
        return httpx.Response(
            200,
            json={
                "requestId": f"reference-{len(requests)}",
                "results": [
                    {
                        "id": REFERENCE_URL,
                        "url": REFERENCE_URL,
                        "title": "Documented reference",
                        "text": "Verified reference text from the selected search provider.",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

        def factory(settings):
            instance = ExaWebClient(settings, client=client)
            clients.append(instance)
            return instance

        monkeypatch.setattr(agent_services, "ExaWebClient", factory)
        yield requests, clients


def research_script(body, requests):
    if body.get("response_format"):
        return extracted_deliverable(body)
    names = {item["function"]["name"] for item in body["tools"]}
    assert {"search_market_data", "read_web_page", "write_file"} <= names
    results = [item for item in body["messages"] if item["role"] == "tool"]
    if not results:
        return {"tool_calls": [tool_call("search_market_data", {"query": QUERY}, "search-source")]}
    if len(results) == 1:
        assert json.loads(results[0]["content"])["result"]["response"]["provider"] == "exa"
        return {"tool_calls": [tool_call("read_web_page", {"url": REFERENCE_URL}, "read-source")]}
    if len(results) == 2:
        assert json.loads(results[-1]["content"])["result"]["response"]["provider"] == "exa"
        return {
            "tool_calls": [
                tool_call(
                    "write_file",
                    {"path": "report.md", "content": f"Reference report: {REFERENCE_URL}\n"},
                    "save-report",
                )
            ]
        }
    return {"content": "Saved the research report with its source evidence."}


@pytest.mark.parametrize("role", ["market_researcher", "data_analyst"])
async def test_research_workers_use_exa_and_replay_completed_sources_after_provider_change(
    tmp_path, monkeypatch, role
):
    kr, work = research_assignment(role)
    async with exa_transport(monkeypatch) as (external_requests, clients):
        async with services_with_provider(tmp_path, research_script) as (
            services,
            storage,
            run,
            requests,
            workspace,
        ):
            configure_exa(services)
            forbid_mcp(monkeypatch, services)
            first = await services.execute(work, kr, Constitution(), [], "", 0)
            assert not first.fallback
            assert (workspace / "report.md").read_text().endswith(REFERENCE_URL + "\n")
            assert len(external_requests) == 2 and len(clients) == 1
            assert len(requests) == 5
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (5, 3)
            operations = list(storage.operations.values())
            assert {json.dumps(item["request"], sort_keys=True) for item in operations} == {
                json.dumps({"query": QUERY}, sort_keys=True),
                json.dumps({"url": REFERENCE_URL}, sort_keys=True),
                json.dumps(
                    {"path": "report.md", "content": f"Reference report: {REFERENCE_URL}\n"},
                    sort_keys=True,
                ),
            }
            artifacts = await storage.list_artifacts(run["run_id"])
            sources = [item for item in artifacts if item["kind"] == "research"]
            assert {item["name"] for item in sources} == {
                "web_search-search-source.json",
                "web_reader-read-source.json",
            }
            assert all(item["artifact_id"] in first.artifact_ids for item in sources)
            for metadata in sources:
                _, content = await services.artifacts.read(metadata["artifact_id"], limit=None)
                assert json.loads(content)["response"]["provider"] == "exa"
            retrieved = [event for event in storage.events if event["activity"] == "reading"]
            assert len(retrieved) == 2
            assert all(
                event["agent_id"] == role and event["kr_id"] == kr.kr_id for event in retrieved
            )
            public_evidence = json.dumps([artifacts, storage.events, operations], default=str)
            assert "fixture-exa-key" not in public_evidence

            # Provider preferences may change between attempts. The old stable
            # operation identity must return the exact recorded Exa evidence.
            services.settings.web_search_provider = "zai_mcp"
            repeated = await services.execute(work, kr, Constitution(), [], "", 0)
            assert repeated.artifact_ids == first.artifact_ids
            assert len(external_requests) == 2 and len(clients) == 1
            assert len(requests) == 10
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (10, 3)
            assert len(await storage.list_artifacts(run["run_id"])) == len(artifacts)
            assert len([event for event in storage.events if event["activity"] == "reading"]) == 2


@pytest.mark.parametrize("caller", ["engineering_head", "planner"])
async def test_leads_delegate_exa_research_and_specialists_consume_its_saved_evidence(
    tmp_path, monkeypatch, caller
):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "specialist": EngineeringSpecialistSpec(
                name="Reference implementation specialist",
                instructions="Read the delegated reference report and save the requested output.",
            )
        }
    )
    report_ids = []
    strategic = StrategicPlan(
        objectives=(
            StrategicObjective(objective_id="objective", title="Output", key_results=(kr,)),
        )
    )

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        prompt = body["messages"][0]["content"]
        names = {item["function"]["name"] for item in body["tools"]}
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if prompt.startswith("You are tools_rd_lead"):
            assert {"search_market_data", "read_web_page"} <= names
            assert "consult_tools_rd" not in names and "register_mission_tool" not in names
            assert names.isdisjoint(PLANNING_TOOL_NAMES - {"run_mission_tool"})
            if not results:
                return {
                    "tool_calls": [tool_call("search_market_data", {"query": QUERY}, "rd-search")]
                }
            if len(results) == 1:
                return {
                    "tool_calls": [tool_call("read_web_page", {"url": REFERENCE_URL}, "rd-read")]
                }
            assert json.loads(results[-1]["content"])["result"]["response"]["provider"] == "exa"
            return {"content": "The documented reference supports this implementation approach."}
        if "consult_tools_rd" in names:
            assert names == PLANNING_TOOL_NAMES
            if not results:
                return {
                    "tool_calls": [
                        tool_call(
                            "consult_tools_rd",
                            {
                                "requirement": "Research the documented reference",
                                "mode": "research",
                            },
                            "delegate-reference",
                        )
                    ]
                }
            report = json.loads(results[0]["content"])["result"]
            assert report["mode"] == "research" and report["requested_by"] == caller
            report_ids.append(report["report_artifact_id"])
            return {
                "content": strategic.model_dump_json()
                if caller == "planner"
                else TacticalPlan(work_packages=(work,)).model_dump_json()
            }
        assert "search_market_data" not in names
        assert names.isdisjoint(PLANNING_TOOL_NAMES - {"run_mission_tool"})
        if not results:
            return {
                "tool_calls": [
                    tool_call("read_artifact", {"artifact_id": report_ids[-1]}, "use-rd-evidence")
                ]
            }
        if len(results) == 1:
            assert "Tools R&D report" in json.loads(results[0]["content"])["content"]
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {
                            "path": "output.txt",
                            "content": "Implementation using the recorded reference",
                        },
                        "write-output",
                    )
                ]
            }
        return {"content": "Saved the implementation output after reading the delegated report."}

    async with exa_transport(monkeypatch) as (external_requests, clients):
        async with services_with_provider(tmp_path, script) as (
            services,
            storage,
            run,
            requests,
            workspace,
        ):
            configure_exa(services)
            forbid_mcp(monkeypatch, services)
            if caller == "planner":
                assert await services.plan("Build a researched output", Constitution()) == list(
                    strategic.objectives
                )
            else:
                assert await services.plan_work(kr, Constitution(), [], "") == [work]
            assert len(external_requests) == 2 and len(clients) == 1
            assert len(requests) == 6
            artifacts = await storage.list_artifacts(run["run_id"])
            source_ids = {item["artifact_id"] for item in artifacts if item["kind"] == "research"}
            assert len(source_ids) == 3  # Two sources and the public consultation receipt.
            _, report = await services.artifacts.read(report_ids[0], limit=None)
            assert "Recorded evidence" in report
            rd_events = [event for event in storage.events if event["agent_id"] == "tools_rd_lead"]
            assert rd_events and all(
                event["data"]["parent_agent_id"] == caller for event in rd_events
            )
            assert all(
                event["kr_id"] == (kr.kr_id if caller != "planner" else "planner-tools")
                for event in rd_events
            )
            assert len([event for event in rd_events if event["activity"] == "reading"]) == 2
            assert not await services.mission_tools().list_tools()
            if caller == "engineering_head":
                result = await services.execute(work, kr, Constitution(), [], "", 0)
                assert result.worker_role == worker_agent_id(run["run_id"], work)
                assert (workspace / "output.txt").read_text().startswith("Implementation")
                assignment_artifacts = [
                    item
                    for item in await storage.list_artifacts(run["run_id"])
                    if item["kind"] == "agent_assignment"
                ]
                assert len(assignment_artifacts) == 1
                _, provenance = await services.artifacts.read(
                    assignment_artifacts[0]["artifact_id"], limit=None
                )
                assert report_ids[0] in provenance
                assert assignment_artifacts[0]["artifact_id"] in result.artifact_ids
                assert len(requests) == 10 and len(external_requests) == 2


async def test_exa_connection_error_is_a_sanitized_blocker_without_mcp_or_fake_evidence(
    tmp_path, monkeypatch
):
    kr, work = research_assignment("market_researcher")

    def script(body, requests):
        return {"tool_calls": [tool_call("search_market_data", {"query": QUERY}, "search-source")]}

    async with exa_transport(monkeypatch, status=429) as (external_requests, clients):
        async with services_with_provider(tmp_path, script) as (
            services,
            storage,
            run,
            requests,
            _,
        ):
            configure_exa(services)
            forbid_mcp(monkeypatch, services)
            with pytest.raises(EscalationSignal) as error:
                await services.execute(work, kr, Constitution(), [], "", 0)
            assert error.value.kind == "missing_resource"
            assert "PRIVATE_EXA_ERROR_BODY" not in error.value.reason
            assert "fixture-exa-key" not in error.value.reason
            assert len(external_requests) == 1 and len(clients) == 1 and len(requests) == 1
            assert not await storage.list_artifacts(run["run_id"])
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (1, 1)
            assert all(item["status"] == "pending" for item in storage.operations.values())


async def test_explicit_mcp_selection_preserves_legacy_tool_arguments_with_an_exa_key(
    tmp_path, monkeypatch
):
    kr, work = research_assignment("market_researcher")
    remote_calls = []

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [tool_call("search_market_data", {"query": QUERY}, "legacy-search")]
            }
        if len(results) == 1:
            return {
                "tool_calls": [tool_call("read_web_page", {"url": REFERENCE_URL}, "legacy-read")]
            }
        return {"content": "Recorded the research sources from the explicitly selected provider."}

    async with exa_transport(monkeypatch) as (external_requests, clients):
        async with services_with_provider(tmp_path, script) as (
            services,
            storage,
            run,
            requests,
            _,
        ):
            configure_exa(services)
            services.settings.web_search_provider = "zai_mcp"

            async def remote(kind, arguments, call_id):
                remote_calls.append((kind, arguments, call_id))
                return {"content": "A legacy source", "url": REFERENCE_URL}

            monkeypatch.setattr(services, "_invoke_mcp", remote)
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            assert remote_calls == [
                ("search", {"search_query": QUERY}, "legacy-search"),
                ("reader", {"url": REFERENCE_URL}, "legacy-read"),
            ]
            assert not external_requests and not clients
            assert len(requests) == 4 and len(result.artifact_ids) == 2
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (4, 2)


@pytest.mark.parametrize("explicit_zai_key", [False, True])
async def test_legacy_mcp_connection_uses_zai_credentials_and_closes_cached_adapters(
    tmp_path, monkeypatch, explicit_zai_key
):
    connections = []
    closed = []

    class Adapter:
        def __init__(self, config):
            connections.append(config)
            self.kind = next(iter(config["mcpServers"]))
            self.remote = SimpleNamespace(name=f"{self.kind}_reference")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(self.kind)

        async def list_tools(self):
            return [self.remote]

    monkeypatch.setattr("langchain.mcp.MCPAdapter", Adapter)
    async with services_with_provider(tmp_path, lambda *_: {}) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        services.settings.exa_api_key = SecretStr("")
        services.settings.web_search_provider = "zai_mcp"
        services.settings.openai_base_url = (
            "https://api.openai.com/v1"
            if explicit_zai_key
            else "https://api.z.ai/api/coding/paas/v4"
        )
        services.settings.openai_api_key = SecretStr(
            "native-openai-fixture" if explicit_zai_key else "configured-zai-fixture"
        )
        services.settings.zai_api_key = SecretStr(
            "explicit-zai-fixture" if explicit_zai_key else ""
        )
        expected_key = "explicit-zai-fixture" if explicit_zai_key else "configured-zai-fixture"
        first = await services._mcp_tool("search")
        assert await services._mcp_tool("search") is first
        assert (await services._mcp_tool("reader")).name == "reader_reference"
        assert len(connections) == 2
        for config in connections:
            server = next(iter(config["mcpServers"].values()))
            assert server["headers"] == {"Authorization": f"Bearer {expected_key}"}
        assert "native-openai-fixture" not in json.dumps(connections)
        assert not requests and not storage.events
        assert (await storage.get_run(run["run_id"]))["tool_calls"] == 0
    assert sorted(closed) == ["reader", "search"]


async def test_native_openai_credentials_do_not_authorize_legacy_zai_mcp(tmp_path, monkeypatch):
    def forbidden_adapter(*args, **kwargs):
        pytest.fail("Missing Z.AI credentials must fail before opening an MCP connection")

    monkeypatch.setattr("langchain.mcp.MCPAdapter", forbidden_adapter)
    async with services_with_provider(tmp_path, lambda *_: {}) as (services, _, _, requests, _):
        services.settings.web_search_provider = "zai_mcp"
        services.settings.openai_base_url = "https://api.openai.com/v1"
        services.settings.openai_api_key = SecretStr("native-openai-fixture")
        services.settings.zai_api_key = SecretStr("")
        with pytest.raises(EscalationSignal) as error:
            await services._mcp_tool("search")
        assert error.value.kind == "missing_resource"
        assert not requests and not services._mcp
        assert "native-openai-fixture" not in error.value.reason
