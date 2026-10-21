"""Concurrent departments keep shared-project mutations exclusive."""

import asyncio

from test_agent_services import assignment, services_with_provider

from org_harness.models import Constitution, Deliverable, TaskSpecialistSpec, worker_agent_id


async def test_sync_workers_in_different_departments_wait_for_shared_project_owner(tmp_path):
    kr, work = assignment()
    research_kr = kr.model_copy(update={"kr_id": "research", "target_department": "research"})
    research = work.model_copy(
        update={"kr_id": "research", "work_package_id": "research", "role": "data_analyst"}
    )
    entered, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active = peak = 0
    finished = []
    async with services_with_provider(tmp_path, lambda *_: {"content": "unused"}) as (
        services,
        _,
        _,
        _,
        workspace,
    ):

        async def execute(selected, key_result, _constitution, _inputs, _feedback, _epoch, host):
            nonlocal active, peak
            assert host.workspace == workspace.resolve()
            active += 1
            peak = max(peak, active)
            try:
                if selected.work_package_id == work.work_package_id:
                    entered.set()
                    await release.wait()
                finished.append(selected.work_package_id)
                return Deliverable(
                    kr_id=key_result.kr_id,
                    department=key_result.target_department,
                    worker_role=host.actor_id,
                    summary="Verified shared-project work",
                    artifact_ids=("verified",),
                )
            finally:
                active -= 1

        emit = services.emit

        async def observe(actor, activity, summary, **data):
            if activity == "waiting" and "exclusive access" in summary:
                queued.set()
            await emit(actor, activity, summary, **data)

        services._execute_worker = execute
        services.emit = observe
        first = asyncio.create_task(services.execute(work, kr, Constitution(), [], "", 0))
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(
            services.execute(research, research_kr, Constitution(), [], "", 0)
        )
        try:
            await asyncio.wait_for(queued.wait(), 2)
            assert active == peak == 1 and not second.done()
        finally:
            release.set()
            await asyncio.gather(first, second)
        assert peak == 1
        assert finished == [work.work_package_id, "research"]


async def test_waiting_for_project_is_not_worker_execution_and_async_staging_can_progress(tmp_path):
    kr, work = assignment()
    staged = work.model_copy(
        update={
            "execution_mode": "async",
            "depends_on": (),
            "specialist": TaskSpecialistSpec(name="Independent analysis", instructions=work.task),
        }
    )
    waiting = asyncio.Event()
    async with services_with_provider(tmp_path, lambda *_: {"content": "unused"}) as (
        services,
        _,
        _,
        _,
        workspace,
    ):
        services.limits = services.limits.model_copy(update={"worker_timeout": 0.03})

        async def execute(selected, key_result, _constitution, _inputs, _feedback, _epoch, host):
            assert (host.workspace != workspace.resolve()) == (selected.execution_mode == "async")
            return Deliverable(
                kr_id=key_result.kr_id,
                department=key_result.target_department,
                worker_role=host.actor_id,
                summary="Completed after obtaining its own workspace",
                artifact_ids=("verified",),
            )

        emit = services.emit

        async def observe(actor, activity, summary, **data):
            if activity == "waiting" and "exclusive access" in summary:
                waiting.set()
            await emit(actor, activity, summary, **data)

        services._execute_worker = execute
        services.emit = observe
        # Represent another department's ownership of the configured project.
        async with services._shared_workspace_lock:
            queued = asyncio.create_task(services.execute(work, kr, Constitution(), [], "", 0))
            await asyncio.wait_for(waiting.wait(), 2)
            result = await services.execute(staged, kr, Constitution(), [], "", 0)
            assert result.artifact_ids == ("verified",)
            await asyncio.sleep(0.05)
            assert not queued.done()
        assert (await queued).artifact_ids == ("verified",)


async def test_async_assignment_metadata_survives_real_tool_events(tmp_path):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "execution_mode": "async",
            "depends_on": (),
            "specialist": TaskSpecialistSpec(name="Independent analysis", instructions=work.task),
        }
    )
    async with services_with_provider(tmp_path, lambda *_: {"content": "unused"}) as (
        services,
        storage,
        run,
        _,
        _,
    ):

        async def execute(selected, key_result, _constitution, _inputs, _feedback, _epoch, host):
            result = await host.write_file("output", "analysis.txt", "Verified staged result")
            await host.read_file("inspect", "analysis.txt")
            return Deliverable(
                kr_id=key_result.kr_id,
                department=key_result.target_department,
                worker_role=host.actor_id,
                summary="Verified staged result",
                artifact_ids=(result["artifact_id"],),
            )

        services._execute_worker = execute
        await services.execute(work, kr, Constitution(), [], "", 0)
        snapshot = await storage.office_snapshot()
        actor = worker_agent_id(run["run_id"], work)
        latest = next(item for item in snapshot["agents"] if item["agent_id"] == actor)
        assert latest["activity"] == "reading"
        assert latest["data"]["task_execution_mode"] == "async"
        assert latest["data"]["work_package_id"] == work.work_package_id
        assert latest["data"]["execution_attempt"] == 0
        assert latest["data"]["depends_on"] == []
