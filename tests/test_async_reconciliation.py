"""Large background joins reconcile every result in bounded durable pages."""

import hashlib
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_agent_services import assignment
from test_async_subagents import real_services

from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.models import Constitution, EscalationSignal, TacticalPlan


def reports():
    return [
        {
            "task_id": hashlib.sha256(str(index).encode()).hexdigest(),
            "agent_id": f"specialist:mission:{index:016d}",
            "parent_agent_id": "engineering_head",
            "status": "succeeded",
            "result": {
                "report": "🙂" * 2000,
                "artifact_ids": [
                    hashlib.sha256(f"{index}:{item}".encode()).hexdigest()[:32] for item in range(8)
                ],
                "report_artifact_id": hashlib.sha256(f"report:{index}".encode()).hexdigest()[:32],
                "tool_ids": [f"tool:{item:032d}" for item in range(8)],
            },
        }
        for index in range(10)
    ]


@pytest.mark.parametrize("automatic", [False, True])
async def test_every_background_result_is_reconciled_with_bounded_pages_and_replayed_receipts(
    tmp_path, monkeypatch, automatic
):
    kr, work = assignment()
    draft = TacticalPlan(work_packages=(work,))
    source = reports()
    seen = []
    saver = InMemorySaver()

    async def script(body):
        if not body.get("response_format"):
            return {"content": draft.model_dump_json()}
        payload = json.loads(body["messages"][-1]["content"])
        page, coverage = payload["background_results"], payload["background_result_coverage"]
        assert payload["original_context"]["kr"] == kr.model_dump(mode="json")
        assert payload["constitution"] == Constitution().model_dump(mode="json")
        assert 1 <= len(page) <= 4
        assert len(json.dumps(page, ensure_ascii=False).encode()) <= 32768
        assert coverage["total"] == 10 and coverage["offset"] == len(seen)
        assert coverage["included"] == len(page)
        assert coverage["has_more"] == (coverage["offset"] + len(page) < 10)
        current = TacticalPlan.model_validate(payload["draft"])
        assert current.work_packages[0].acceptance_criteria == work.acceptance_criteria
        assert all(item in current.work_packages[0].task for item in seen)
        seen.extend(item["task_id"] for item in page)
        updated = current.work_packages[0].model_copy(
            update={
                "task": current.work_packages[0].task
                + "\nVerified background references: "
                + ",".join(item["task_id"] for item in page)
            }
        )
        return {"content": TacticalPlan(work_packages=(updated,)).model_dump_json()}

    limits = (
        {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}
        if automatic
        else None
    )
    async with real_services(tmp_path, monkeypatch, script, limits=limits, saver=saver) as (
        services,
        storage,
        run,
        _requests,
    ):

        async def join(caller, host, key_result):
            assert caller == host.role == "engineering_head"
            assert key_result == kr and host.kr_id == kr.kr_id
            return source

        monkeypatch.setattr(services.async_subagents(), "join", join)
        completed = await services.plan_work(kr, Constitution(), [], "")
        assert seen == [item["task_id"] for item in source]
        assert all(item in completed[0].task for item in seen)
        receipts = await storage.list_operations(run["run_id"], kind="planning_async_join")
        assert len(receipts) >= 3 and all(item["status"] == "done" for item in receipts)
        initial_calls = (await storage.get_run(run["run_id"]))["model_calls"]

    # A fresh owner still uses every persisted page, without another R&D/reconcile
    # model request. Finite leads retain their existing one-call draft behavior.
    current = await storage.get_run(run["run_id"])
    async with real_services(
        tmp_path, monkeypatch, script, storage=storage, run=current, saver=saver
    ) as (services, _storage, _run, _requests):
        monkeypatch.setattr(services.async_subagents(), "join", join)
        replayed = await services.plan_work(kr, Constitution(), [], "")
        assert replayed == completed
        assert seen == [item["task_id"] for item in source]
        assert (await storage.get_run(run["run_id"]))["model_calls"] == initial_calls + (
            0 if automatic else 1
        )
        assert len(await storage.list_operations(run["run_id"], kind="planning_async_join")) == len(
            receipts
        )


@pytest.mark.parametrize("kind", ["provider_error", "invalid_model_output"])
async def test_autonomous_reconciliation_failure_resumes_pending_page_without_repeating_saved_pages(
    tmp_path, monkeypatch, kind
):
    kr, work = assignment()
    draft = TacticalPlan(work_packages=(work,))
    source = reports()
    seen = []
    saver = InMemorySaver()

    async def script(body):
        if not body.get("response_format"):
            return {"content": draft.model_dump_json()}
        payload = json.loads(body["messages"][-1]["content"])
        assert payload["background_result_coverage"]["offset"] == len(seen)
        current = TacticalPlan.model_validate(payload["draft"])
        assert all(task_id in current.work_packages[0].task for task_id in seen)
        seen.extend(item["task_id"] for item in payload["background_results"])
        updated = current.work_packages[0].model_copy(
            update={"task": work.task + "\nReconciled references: " + ",".join(seen)}
        )
        return {"content": TacticalPlan(work_packages=(updated,)).model_dump_json()}

    async def join(*_args):
        return source

    limits = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}
    async with real_services(tmp_path, monkeypatch, script, limits=limits, saver=saver) as (
        services,
        storage,
        run,
        _requests,
    ):
        monkeypatch.setattr(services.async_subagents(), "join", join)
        structured = services.structured

        async def unavailable(schema, instruction, payload, **kwargs):
            if payload.get("background_result_coverage", {}).get("offset", 0) > 0:
                raise EscalationSignal(kind, "Safe temporary provider diagnostic")
            return await structured(schema, instruction, payload, **kwargs)

        monkeypatch.setattr(services, "structured", unavailable)
        with pytest.raises(AutonomousCheckpointYield) as caught:
            await services.plan_work(kr, Constitution(), [], "")
        assert caught.value.recoverable_failure is True
        assert caught.value.delay_seconds > 0
        assert 0 < len(seen) < len(source)
        operations = await storage.list_operations(run["run_id"], kind="planning_async_join")
        completed_page = next(item for item in operations if item["status"] == "done")
        pending_page = next(item for item in operations if item["status"] == "pending")
        calls_before = (await storage.get_run(run["run_id"]))["model_calls"]

    current = await storage.get_run(run["run_id"])
    async with real_services(
        tmp_path, monkeypatch, script, storage=storage, run=current, saver=saver
    ) as (services, _storage, _run, requests):
        monkeypatch.setattr(services.async_subagents(), "join", join)
        result = await services.plan_work(kr, Constitution(), [], "")
        assert seen == [item["task_id"] for item in source]
        assert all(task_id in result[0].task for task_id in seen)
        operations = await storage.list_operations(run["run_id"], kind="planning_async_join")
        assert all(item["status"] == "done" for item in operations)
        assert await storage.get_operation(completed_page["operation_id"]) == completed_page
        assert (await storage.get_operation(pending_page["operation_id"]))["status"] == "done"
        # Only previously unfinished pages request a model response. The private
        # planner and the completed first page both replay their saved results.
        assert len(requests) == len(operations) - 1
        assert (await storage.get_run(run["run_id"]))["model_calls"] == calls_before + len(requests)


@pytest.mark.parametrize("kind", ["provider_error", "invalid_model_output"])
async def test_finite_reconciliation_preserves_provider_failure_and_pending_receipt(
    tmp_path, monkeypatch, kind
):
    kr, work = assignment()
    draft = TacticalPlan(work_packages=(work,))

    async def script(_body):
        return {"content": draft.model_dump_json()}

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, run, _requests):

        async def join(*_args):
            return reports()

        async def unavailable(*_args, **_kwargs):
            raise EscalationSignal(kind, "Safe temporary provider diagnostic")

        monkeypatch.setattr(services.async_subagents(), "join", join)
        monkeypatch.setattr(services, "structured", unavailable)
        with pytest.raises(EscalationSignal) as caught:
            await services.plan_work(kr, Constitution(), [], "")
        assert caught.value.kind == kind
        operations = await storage.list_operations(run["run_id"], kind="planning_async_join")
        assert len(operations) == 1 and operations[0]["status"] == "pending"


@pytest.mark.parametrize("automatic", [False, True])
async def test_oversized_public_report_is_rejected_before_any_reconciliation_request(
    tmp_path, monkeypatch, automatic
):
    kr, work = assignment()
    draft = TacticalPlan(work_packages=(work,))

    async def script(body):
        assert not body.get("response_format")
        return {"content": draft.model_dump_json()}

    limits = (
        {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}
        if automatic
        else None
    )
    async with real_services(tmp_path, monkeypatch, script, limits=limits) as (
        services,
        storage,
        run,
        requests,
    ):

        async def join(*_args):
            report = reports()[0]
            report["result"]["report"] = "🙂" * 10000
            return [report]

        monkeypatch.setattr(services.async_subagents(), "join", join)
        with pytest.raises(EscalationSignal, match="bounded public contract"):
            await services.plan_work(kr, Constitution(), [], "")
        assert len(requests) == 1
        assert await storage.list_operations(run["run_id"], kind="planning_async_join") == []
