"""A growing mission catalog stays discoverable without enlarging every prompt."""

import json

import pytest
from test_agent_services import assignment, services_with_provider, tool_call
from test_dynamic_services import extracted_deliverable
from test_mission_tools import SCHEMA, SOURCE, environment, register

from org_harness.agent_services import ToolsResearchResult, WorkerHostTools
from org_harness.mission_tools import CATALOG_PAGE_BYTES, MissionToolCatalog
from org_harness.models import Constitution, RunLimits, StrategicObjective, StrategicPlan
from org_harness.storage import PostgresStorage
from org_harness.tools import Artifacts
from org_harness.worker import command_recovery_summary

UNLIMITED = RunLimits(max_model_calls=None, worker_model_calls=None, max_tool_calls=None)


async def thirteen_versions(tmp_path, storage=None):
    storage, run, artifacts, catalog, rd, host = await environment(tmp_path, storage)
    # The existing catalog object retains the finite creation snapshot. Current
    # authoritative limits, rather than stale service state, govern registration.
    current = await storage.update_run(run["run_id"], limits=UNLIMITED.model_dump(mode="json"))
    versions = []
    for index in range(13):
        if index == 12:
            (rd.workspace / "double.py").write_text(SOURCE.replace("*2", "*3"))
        result = await register(
            catalog,
            rd,
            call=f"version-{index}",
            description=f"Integer transformation version {index}",
        )
        assert result.get("smoke_test_passed"), result
        versions.append(result)
    return storage, current, artifacts, catalog, versions


async def assert_thirteen_versions(tmp_path, url=None):
    storage = None
    if url is not None:
        storage = PostgresStorage(url)
        await storage.open()
        await storage.migrate()
    try:
        storage, run, artifacts, catalog, versions = await thirteen_versions(tmp_path, storage)
        if url is not None:
            await storage.close()
            storage = PostgresStorage(url)
            await storage.open()
            artifacts = Artifacts(storage, tmp_path, run["run_id"])
        catalog = MissionToolCatalog(None, storage, run, artifacts)
        preview = await catalog.preview()
        assert preview["total"] == 13 and preview["has_more"]
        assert len(preview["tools"]) == 3
        assert preview["tools"][0]["tool_id"] == versions[-1]["tool_id"]
        assert all("input_schema" not in item for item in preview["tools"])
        discovered, offset = [], 0
        while True:
            page = await catalog.discover_tools(offset=offset)
            assert len(json.dumps(page, ensure_ascii=True)) <= CATALOG_PAGE_BYTES
            assert page["total"] == 13 and page["discovery_only"]
            assert all(item["input_schema"] == SCHEMA for item in page["tools"])
            discovered.extend(item["tool_id"] for item in page["tools"])
            if not page["has_more"]:
                assert page["next_offset"] is None
                break
            offset = page["next_offset"]
        assert discovered == [item["tool_id"] for item in versions]
        match = await catalog.discover_tools(query=versions[0]["tool_id"])
        assert len(match["tools"]) == match["total"] == 1
        assert not (await catalog.discover_tools(query="missing capability"))["tools"]

        async def emit(*args, **kwargs):
            pass

        worker = WorkerHostTools(
            storage,
            artifacts,
            run,
            kr_id="analysis",
            role="data_analyst",
            department="research",
            epoch=0,
            emit=emit,
        )
        old = await catalog.invoke(
            worker, "old-version", tool_id=versions[0]["tool_id"], arguments={"value": 4}
        )
        new = await catalog.invoke(
            worker, "new-version", tool_id=versions[-1]["tool_id"], arguments={"value": 4}
        )
        assert old["output"] == {"doubled": 8} and new["output"] == {"doubled": 12}
    finally:
        if storage is not None:
            await storage.close()


async def test_thirteen_versions_remain_paged_searchable_and_invokable(tmp_path):
    await assert_thirteen_versions(tmp_path)


@pytest.mark.integration
async def test_thirteen_versions_survive_postgres_catalog_reopen(tmp_path, postgres_url):
    await assert_thirteen_versions(tmp_path, postgres_url)


async def test_finite_registration_still_stops_at_twelve_without_testing_a_thirteenth(tmp_path):
    storage, run, _, catalog, rd, _ = await environment(tmp_path)
    for index in range(12):
        assert (await register(catalog, rd, call=f"version-{index}"))["smoke_test_passed"]
    receipts = [
        item
        for item in await storage.list_artifacts(run["run_id"])
        if item["kind"] == "command_result"
    ]
    result = await register(catalog, rd, call="version-12")
    assert result["error"] == "ExpectedToolInputError"
    assert "registered-tool limit" in result["detail"]
    assert len(await catalog.list_tools()) == 12
    assert len(
        [
            item
            for item in await storage.list_artifacts(run["run_id"])
            if item["kind"] == "command_result"
        ]
    ) == len(receipts)


async def seed_descriptions(services, count=13):
    for index in range(count):
        definition = {
            "tool_id": f"tool:{index:032d}",
            "name": f"version_{index}",
            "description": "A bounded transformation " + str(index),
            "input_schema": {**SCHEMA, "description": "schema marker " + "x" * 7000},
        }
        await services.artifacts.save(
            f"version_{index}.tool.json",
            json.dumps(definition),
            kind="mission_tool_definition",
            tool_definition=definition,
        )


async def test_catalog_pages_stop_on_byte_boundary_without_truncating_schemas(tmp_path):
    async with services_with_provider(tmp_path, lambda *_: {"content": "unused"}) as (services, *_):
        await seed_descriptions(services)
        offset, ids = 0, []
        while True:
            page = await services.mission_tools().discover_tools(offset=offset, limit=5)
            assert 1 <= len(page["tools"]) < 5
            assert len(json.dumps(page, ensure_ascii=True)) <= CATALOG_PAGE_BYTES
            assert all(len(item["input_schema"]["description"]) > 7000 for item in page["tools"])
            ids.extend(item["tool_id"] for item in page["tools"])
            if not page["has_more"]:
                break
            offset = page["next_offset"]
        assert len(ids) == len(set(ids)) == 13


@pytest.mark.parametrize("automatic", [True, False])
async def test_research_analyst_reuses_an_immutable_registered_tool_through_real_agent(
    tmp_path, automatic
):
    kr, work = assignment()
    kr = kr.model_copy(update={"target_department": "research"})
    work = work.model_copy(update={"role": "data_analyst"})
    tool_id = None

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        names = {item["function"]["name"] for item in body["tools"]}
        assert "run_mission_tool" in names and "consult_tools_rd" not in names
        assert ("list_mission_tools" in names) == automatic
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if automatic and not results:
            return {"tool_calls": [tool_call("list_mission_tools", {"query": tool_id}, "discover")]}
        if not results or results[-1]["tool_call_id"] == "discover":
            return {
                "tool_calls": [
                    tool_call(
                        "run_mission_tool",
                        {"tool_id": tool_id, "arguments": {"value": 9}},
                        "invoke",
                    )
                ]
            }
        if results[-1]["tool_call_id"] == "invoke":
            output = json.loads(results[-1]["content"])["output"]
            assert output == {"doubled": 18}
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {"path": "analysis.json", "content": json.dumps(output)},
                        "save",
                    )
                ]
            }
        return {"content": "Recorded the numeric analysis result."}

    async with services_with_provider(
        tmp_path, script, limits=UNLIMITED.model_dump(mode="json") if automatic else None
    ) as (services, storage, run, requests, workspace):
        rd = WorkerHostTools(
            storage,
            services.artifacts,
            run,
            kr_id=kr.kr_id,
            department="engineering",
            epoch=0,
            role="tools_rd_lead",
            emit=services.emit,
        )
        (rd.workspace / "double.py").write_text(SOURCE)
        result = await register(services.mission_tools(), rd)
        tool_id = result["tool_id"]
        # Discovery and invocations use the stored source, not mutable workspace code.
        (rd.workspace / "double.py").write_text("raise RuntimeError('tampered workspace')")
        deliverable = await services.execute(work, kr, Constitution(), [], "", 0)
        assert json.loads((workspace / "analysis.json").read_text()) == {"doubled": 18}
        assert deliverable.worker_role == "data_analyst" and deliverable.artifact_ids
        proof = [
            item
            for item in await storage.list_artifacts(run["run_id"])
            if item["kind"] == "mission_tool_use"
        ]
        assert len(proof) == 1 and proof[0]["department"] == "research"


@pytest.mark.parametrize("automatic", [True, False])
async def test_planner_third_rd_consultation_and_returned_catalog_are_truthful_and_bounded(
    tmp_path, automatic
):
    kr, _ = assignment()
    plan = StrategicPlan(
        objectives=(
            StrategicObjective(objective_id="objective", title="Output", key_results=(kr,)),
        )
    )
    consultations = []

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        prompt = body["messages"][0]["content"]
        results = [item for item in body["messages"] if item["role"] == "tool"]
        names = {item["function"]["name"] for item in body["tools"]}
        if prompt.startswith("You are tools_rd_lead"):
            assert "consult_tools_rd" not in names
            assert ("list_mission_tools" in names) == automatic
            assert "schema marker" not in prompt
            if not results:
                return {
                    "tool_calls": [
                        tool_call(
                            "write_file",
                            {"path": "finding.txt", "content": "Recorded R&D finding"},
                            "rd-output",
                        )
                    ]
                }
            return {"content": "Research findings recorded; existing tools are sufficient."}
        assert ("list_mission_tools" in names) == automatic
        assert "schema marker" not in prompt
        if len(results) < 3:
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {"requirement": f"Research capability {len(results)}", "mode": "research"},
                        f"consult-{len(results)}",
                    )
                ]
            }
        consultations.extend(json.loads(item["content"]) for item in results)
        return {"content": plan.model_dump_json()}

    async with services_with_provider(
        tmp_path, script, limits=UNLIMITED.model_dump(mode="json") if automatic else None
    ) as (services, storage, run, requests, workspace):
        await seed_descriptions(services)
        assert await services.plan("Plan useful output", Constitution()) == list(plan.objectives)
        assert len(consultations) == 3
        if automatic:
            for value in consultations:
                report = ToolsResearchResult.model_validate(value["result"])
                assert report.tool_count == 13 and report.tools_has_more
                assert len(report.tools) == 3
                assert all("input_schema" not in item for item in report.tools)
        else:
            assert consultations[-1]["error"] == "ExpectedToolInputError"
            assert "consultation limit" in consultations[-1]["detail"]


@pytest.mark.parametrize(
    "actor", ["worker", "tools_rd_lead", "data_analyst", "market_researcher", "narrowed"]
)
async def test_autonomous_discovery_binding_is_scoped_and_initial_prompt_stays_compact(
    tmp_path, actor
):
    from org_harness.models import TaskSpecialistSpec

    kr, work = assignment()
    if actor in {"data_analyst", "market_researcher"}:
        kr = kr.model_copy(update={"target_department": "research"})
        work = work.model_copy(update={"role": actor})
    if actor == "narrowed":
        work = work.model_copy(
            update={
                "specialist": TaskSpecialistSpec(
                    name="Writer", instructions="Write output", tools=("write_file",)
                )
            }
        )
    expected = actor not in {"market_researcher", "narrowed"}

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        prompt = body["messages"][0]["content"]
        names = {item["function"]["name"] for item in body["tools"]}
        assert ("list_mission_tools" in names) == expected
        assert ("run_mission_tool" in names) == expected
        assert "consult_tools_rd" not in names
        assert "schema marker" not in prompt and len(prompt) < 15000
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if expected and not results:
            assert '"total": 13' in prompt and '"has_more": true' in prompt
            return {
                "tool_calls": [tool_call("list_mission_tools", {"query": "version_0", "limit": 5})]
            }
        if results and results[-1]["tool_call_id"] == "tool-1":
            page = json.loads(results[-1]["content"])
            assert page["total"] == 1 and page["tools"][0]["input_schema"]["required"] == ["value"]
            return {
                "tool_calls": [
                    tool_call(
                        "write_file", {"path": "result.txt", "content": "Honest output"}, "output"
                    )
                ]
            }
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "write_file", {"path": "result.txt", "content": "Honest output"}, "output"
                    )
                ]
            }
        return {"content": "Created the required output artifact."}

    async with services_with_provider(
        tmp_path, script, limits=UNLIMITED.model_dump(mode="json")
    ) as (services, storage, run, requests, workspace):
        await seed_descriptions(services)
        if actor == "tools_rd_lead":
            host = WorkerHostTools(
                storage,
                services.artifacts,
                run,
                kr_id=kr.kr_id,
                department="engineering",
                epoch=0,
                role=actor,
                emit=services.emit,
            )
            await services._execute_worker(
                work, kr, Constitution(), [], "", 0, host, actor=actor, rd_mode="research"
            )
        else:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert not any(
            item["kind"] == "mission_tool_use"
            for item in await storage.list_artifacts(run["run_id"])
        )


def test_command_recovery_projection_omits_raw_output_and_retains_truthful_receipt_references():
    raw = {
        "operation_id": "operation",
        "result": {
            "exit_code": 125,
            "interrupted": True,
            "effects_uncertain": True,
            "execution_stopped": False,
            "artifact_ids": ["receipt"],
            "stdout": "x" * 100000,
            "stderr": "private raw output",
            "recovery_guidance": "g" * 4000,
        },
    }
    summary = command_recovery_summary(raw)
    assert summary["result"]["exit_code"] == 125 and not summary["result"]["execution_stopped"]
    assert summary["result"]["artifact_ids"] == ["receipt"]
    assert len(summary["result"]["recovery_guidance"]) == 2000
    assert "stdout" not in summary["result"] and "stderr" not in summary["result"]
    assert len(raw["result"]["stdout"]) == 100000
