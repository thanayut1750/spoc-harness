"""Missing individual pages stay recoverable inside real worker and R&D agent loops."""

import copy
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from test_agent_services import assignment, services_with_provider, tool_call
from test_exa_agent_tools import (
    configure_exa,
    extracted_deliverable,
    forbid_mcp,
    research_assignment,
)

from org_harness import agent_services
from org_harness.models import (
    Constitution,
    EscalationSignal,
    StrategicObjective,
    StrategicPlan,
    TacticalPlan,
)
from org_harness.web_search import ExaWebClient

MISSING_URL = "https://docs.example.org/outdated-page"
CANONICAL_URL = "https://docs.example.org/current-page"


@asynccontextmanager
async def page_transport(monkeypatch, *, fatal_response=None):
    requested_urls = []

    def response(request):
        assert request.url == "https://api.exa.ai/contents"
        payload = json.loads(request.content)
        url = payload["urls"][0]
        requested_urls.append(url)
        if url == MISSING_URL:
            if fatal_response is not None:
                return fatal_response
            return httpx.Response(
                200,
                json={
                    "results": [],
                    "statuses": [
                        {
                            "id": url,
                            "status": "error",
                            "error": {
                                "tag": "CRAWL_NOT_FOUND",
                                "httpStatusCode": 404,
                                "message": "PRIVATE_CRAWLER_RESPONSE",
                            },
                        }
                    ],
                },
            )
        assert url == CANONICAL_URL
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": url, "title": "Canonical documentation", "text": "Verified content."}
                ],
                "statuses": [{"id": url, "status": "success"}],
            },
        )

    async def no_direct_fallback(*args, **kwargs):
        pytest.fail("A recoverable Exa page failure must not silently fetch another provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        monkeypatch.setattr(
            agent_services, "ExaWebClient", lambda settings: ExaWebClient(settings, client=client)
        )
        monkeypatch.setattr(agent_services, "read_reference_page", no_direct_fallback)
        yield requested_urls


def assert_missing_page_result(message):
    value = json.loads(message["content"])
    assert value["error"] == "ExaContentUnavailable"
    assert "artifact_id" not in value
    assert "PRIVATE_CRAWLER_RESPONSE" not in value["detail"]
    assert "fixture-exa-key" not in value["detail"]
    return value


def assert_canonical_source(message):
    value = json.loads(message["content"])
    assert value["artifact_id"]
    source = value["result"]["response"]
    assert source["provider"] == "exa"
    assert source["requested_url"] == CANONICAL_URL
    assert source["results"][0]["text"] == "Verified content."


@pytest.mark.parametrize("role", ["market_researcher", "data_analyst"])
async def test_research_recovers_with_canonical_page_and_replays_missing_page_error(
    tmp_path, monkeypatch, role
):
    kr, work = research_assignment(role)

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [message for message in body["messages"] if message["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [tool_call("read_web_page", {"url": MISSING_URL}, "missing-page")]
            }
        if len(results) == 1:
            assert_missing_page_result(results[0])
            return {
                "tool_calls": [tool_call("read_web_page", {"url": CANONICAL_URL}, "canonical-page")]
            }
        if len(results) == 2:
            assert_canonical_source(results[-1])
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {"path": "report.md", "content": f"Verified report: {CANONICAL_URL}\n"},
                        "report",
                    )
                ]
            }
        return {"content": "Saved the report using the corrected canonical reference."}

    async with page_transport(monkeypatch) as requested_urls:
        async with services_with_provider(tmp_path, script) as (
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
            assert requested_urls == [MISSING_URL, CANONICAL_URL]
            assert (workspace / "report.md").read_text().endswith(CANONICAL_URL + "\n")
            operations = copy.deepcopy(storage.operations)
            assert len(operations) == 3 and all(
                item["status"] == "done" for item in operations.values()
            )
            failure = next(
                item for item in operations.values() if item["request"] == {"url": MISSING_URL}
            )
            assert failure["result"]["error"] == "ExaContentUnavailable"
            assert "artifact_id" not in failure["result"]
            artifacts = await storage.list_artifacts(run["run_id"])
            sources = [item for item in artifacts if item["kind"] == "research"]
            assert len(sources) == 1 and sources[0]["name"] == "web_reader-canonical-page.json"
            assert sources[0]["artifact_id"] in first.artifact_ids
            _, content = await services.artifacts.read(sources[0]["artifact_id"], limit=None)
            assert json.loads(content)["url"] == CANONICAL_URL
            assert "PRIVATE_CRAWLER_RESPONSE" not in json.dumps(artifacts + storage.events)
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (5, 3)
            assert not await storage.uncertain_operations(run["run_id"])

            repeated = await services.execute(work, kr, Constitution(), [], "", 0)
            assert repeated.artifact_ids == first.artifact_ids
            assert requested_urls == [MISSING_URL, CANONICAL_URL]
            assert storage.operations == operations
            assert len(await storage.list_artifacts(run["run_id"])) == len(artifacts)
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (10, 3)
            assert len(requests) == 10


@pytest.mark.parametrize("caller", ["planner", "engineering_head"])
async def test_nested_rd_recovers_missing_page_before_returning_evidence_backed_plan(
    tmp_path, monkeypatch, caller
):
    kr, work = assignment()
    strategic = StrategicPlan(
        objectives=(
            StrategicObjective(objective_id="objective", title="Output", key_results=(kr,)),
        )
    )
    reports = []

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [message for message in body["messages"] if message["role"] == "tool"]
        if body["messages"][0]["content"].startswith("You are tools_rd_lead"):
            if not results:
                return {
                    "tool_calls": [
                        tool_call("read_web_page", {"url": MISSING_URL}, "rd-missing-page")
                    ]
                }
            if len(results) == 1:
                assert_missing_page_result(results[0])
                return {
                    "tool_calls": [
                        tool_call("read_web_page", {"url": CANONICAL_URL}, "rd-canonical-page")
                    ]
                }
            assert_canonical_source(results[-1])
            return {"content": "The canonical reference documents the required capability."}
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {"requirement": "Research the available reference", "mode": "research"},
                        "consult-reference",
                    )
                ]
            }
        consultation = json.loads(results[0]["content"])["result"]
        assert consultation["requested_by"] == caller
        reports.append(consultation["report_artifact_id"])
        return {
            "content": strategic.model_dump_json()
            if caller == "planner"
            else TacticalPlan(work_packages=(work,)).model_dump_json()
        }

    async with page_transport(monkeypatch) as requested_urls:
        async with services_with_provider(tmp_path, script) as (
            services,
            storage,
            run,
            requests,
            _,
        ):
            configure_exa(services)
            forbid_mcp(monkeypatch, services)

            async def plan():
                if caller == "planner":
                    return await services.plan("Build the requested output", Constitution())
                return await services.plan_work(kr, Constitution(), [], "")

            assert await plan()
            assert requested_urls == [MISSING_URL, CANONICAL_URL] and len(requests) == 6
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (6, 4)
            artifacts = await storage.list_artifacts(run["run_id"])
            assert not any(item["name"] == "web_reader-rd-missing-page.json" for item in artifacts)
            canonical = next(
                item for item in artifacts if item["name"] == "web_reader-rd-canonical-page.json"
            )
            _, report = await services.artifacts.read(reports[0], limit=None)
            assert canonical["artifact_id"] in report
            rd_events = [event for event in storage.events if event["agent_id"] == "tools_rd_lead"]
            assert rd_events and not any(event["activity"] == "error" for event in rd_events)
            assert all(event["data"]["parent_agent_id"] == caller for event in rd_events)
            assert any(event["activity"] == "completed" for event in rd_events)
            expected_kr = kr.kr_id if caller == "engineering_head" else "planner-tools"
            assert all(event["kr_id"] == expected_kr for event in rd_events)

            assert await plan()
            assert reports == [reports[0], reports[0]]
            assert requested_urls == [MISSING_URL, CANONICAL_URL] and len(requests) == 8
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (8, 4)
            assert len(await storage.list_artifacts(run["run_id"])) == len(artifacts)


async def test_missing_page_does_not_cancel_a_parallel_successful_source(tmp_path, monkeypatch):
    kr, work = research_assignment("market_researcher")

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [message for message in body["messages"] if message["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call("read_web_page", {"url": MISSING_URL}, "missing-page"),
                    tool_call("read_web_page", {"url": CANONICAL_URL}, "canonical-page"),
                ]
            }
        if len(results) == 2:
            by_id = {message["tool_call_id"]: message for message in results}
            assert_missing_page_result(by_id["missing-page"])
            assert_canonical_source(by_id["canonical-page"])
            return {
                "tool_calls": [
                    tool_call(
                        "write_file", {"path": "report.md", "content": "Verified report"}, "report"
                    )
                ]
            }
        return {"content": "Saved a report using the available canonical source."}

    async with page_transport(monkeypatch) as requested_urls:
        async with services_with_provider(tmp_path, script) as (
            services,
            storage,
            run,
            requests,
            workspace,
        ):
            configure_exa(services)
            forbid_mcp(monkeypatch, services)
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            assert not result.fallback and (workspace / "report.md").is_file()
            assert sorted(requested_urls) == sorted([MISSING_URL, CANONICAL_URL])
            assert len(requests) == 4
            assert all(operation["status"] == "done" for operation in storage.operations.values())
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (4, 3)
            sources = [
                item
                for item in await storage.list_artifacts(run["run_id"])
                if item["kind"] == "research"
            ]
            assert len(sources) == 1 and sources[0]["artifact_id"] in result.artifact_ids


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="PRIVATE_SERVICE_RESPONSE"),
        httpx.Response(429, text="PRIVATE_SERVICE_RESPONSE"),
        httpx.Response(
            200,
            json={
                "results": [],
                "statuses": [
                    {
                        "id": MISSING_URL,
                        "status": "success",
                        "error": {"tag": "PRIVATE_SERVICE_RESPONSE"},
                    }
                ],
            },
        ),
    ],
    ids=["authorization", "quota", "corrupt-status"],
)
async def test_service_failures_during_read_remain_fatal_without_fallback(
    tmp_path, monkeypatch, response
):
    kr, work = research_assignment("market_researcher")

    def script(body, requests):
        return {"tool_calls": [tool_call("read_web_page", {"url": MISSING_URL}, "read-source")]}

    async with page_transport(monkeypatch, fatal_response=response) as requested_urls:
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
            assert "PRIVATE_SERVICE_RESPONSE" not in error.value.reason
            assert "fixture-exa-key" not in error.value.reason
            assert requested_urls == [MISSING_URL] and len(requests) == 1
            assert not await storage.list_artifacts(run["run_id"])
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (1, 1)
            assert all(item["status"] == "pending" for item in storage.operations.values())
