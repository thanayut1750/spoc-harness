"""Bound review context without inventing proof or weakening local validation."""

import json
from pathlib import Path

import pytest
from test_agent_services import approve, assignment, services_with_provider

from org_harness.agent_services import ToolsResearchResult
from org_harness.models import Constitution, Deliverable, EscalationSignal, RunLimits

UNLIMITED = RunLimits(max_model_calls=None, worker_model_calls=None, max_tool_calls=None)


@pytest.mark.parametrize("proof_present", [True, False])
async def test_large_evidence_packet_is_bounded_transparent_and_keeps_tail_proof(
    tmp_path, proof_present
):
    kr, _ = assignment()
    criterion = "Recorded tail proof confirms the requested result"
    seen = []

    def script(body, requests):
        payload = json.loads(body["messages"][-1]["content"])
        evidence, coverage = payload["recorded_artifact_evidence"], payload["evidence_coverage"]
        seen.append(coverage)
        assert coverage["total"] == 20 and coverage["included"] == 16
        assert coverage["omitted"] == 4 and coverage["has_more"]
        assert sum(len(item["content"].encode()) for item in evidence) <= 48000
        assert coverage["content_bytes"] <= 48000
        assert all(len(item["content"]) <= 12000 and item["content_truncated"] for item in evidence)
        assert all(item["excerpt_ranges"][0][0] == 0 for item in evidence)
        assert all(item["excerpt_ranges"][-1][-1] == item["total_characters"] for item in evidence)
        assert "omitted artifacts and metadata are not proof" in body["messages"][0]["content"]
        display = payload["deliverable"]
        assert len(display["summary"]) == 6000 and display["summary_truncated"]
        assert display["summary_characters"] == 20000
        assert len(display["artifact_ids"]) == 16 and display["artifact_count"] == 20
        assert display["artifacts_has_more"]
        assert len(display["evidence"]) == 8 and all(
            len(item) == 1000 for item in display["evidence"]
        )
        assert display["evidence_count"] == 20 and display["evidence_truncated"]
        history = payload["recorded_check_history"]
        assert len(history) == 64
        assert all(len(item["command"]) == 500 and item["command_truncated"] for item in history)
        assert all(item["command_characters"] > 10000 for item in history)
        dynamic = {
            key: value
            for key, value in payload.items()
            if key not in {"constitution", "acceptance_criteria"}
        }
        assert len(json.dumps(dynamic, ensure_ascii=False).encode()) < 150000
        passed = any("ACTUAL_TAIL_PROOF" in item["content"] for item in evidence)
        result = approve((criterion,))
        if not passed:
            result.update(
                passed_kr_criteria=False,
                score=0,
                criterion_results={criterion: False},
                recommended_action="retry_worker",
                feedback="Required proof is absent; omitted content cannot establish success",
            )
        return {"content": json.dumps(result)}

    async with services_with_provider(tmp_path, script) as (services, *_):
        ids = []
        for index in range(20):
            body = (
                "Head of recorded output\n"
                + "🙂" * 17500
                + ("\nACTUAL_TAIL_PROOF" if proof_present else "\nUnverified ending")
            )
            artifact = await services.artifacts.save(
                f"output-{index}.txt", body, kind="source", kr_id=kr.kr_id, scope="review-proof"
            )
            ids.append(artifact["artifact_id"])
        for index in range(80):
            await services.artifacts.save(
                f"command-{index}.json",
                json.dumps({"exit_code": 0}),
                kind="command_result",
                kr_id=kr.kr_id,
                scope="review-proof",
                exit_code=0,
                command="command " + "x" * 10000,
            )
        deliverable = Deliverable(
            kr_id=kr.kr_id,
            department="engineering",
            worker_role="backend_coder",
            summary="s" * 20000,
            evidence=("e" * 3000,) * 20,
            artifact_ids=tuple(ids),
        )
        original = deliverable.model_dump()
        result = await services.evaluate(
            deliverable,
            (criterion,),
            Constitution(),
        )
        assert result.deterministic_checks_passed
        assert result.passed_kr_criteria is proof_present
        assert deliverable.model_dump() == original
        assert len(seen) == 1


async def seed_consultations(services, kr, count=12):
    reports = []
    for index in range(count):
        rd_scope = json.dumps([services.run_id, kr.kr_id, index, "tools_rd_lead"])
        report = await services.artifacts.save(
            "report.md",
            f"Findings for consultation {index}",
            kind="source",
            kr_id=kr.kr_id,
            scope=rd_scope,
        )
        evidence = [report["artifact_id"]]
        for number in range(9):
            item = await services.artifacts.save(
                f"source-{number}.txt",
                f"Evidence {index}.{number}",
                kind="source",
                kr_id=kr.kr_id,
                scope=rd_scope,
            )
            evidence.append(item["artifact_id"])
        public = ToolsResearchResult(
            report=f"Consultation {index:02d}: " + "r" * 2000,
            artifact_ids=tuple(evidence),
            report_artifact_id=report["artifact_id"],
            mode="research",
            requested_by="engineering_head",
        )
        host = services._planning_host("engineering_head", kr, payload={"round": index})
        artifact = await services.artifacts.save(
            f"tools_rd_consultation-{index}.json",
            public.model_dump_json(),
            kind="research",
            kr_id=kr.kr_id,
            scope=host.scope,
            created_at=f"2026-10-20T00:00:{index:02d}+00:00",
        )
        reports.append((report, artifact))
    return reports


@pytest.mark.parametrize("automatic", [True, False])
async def test_assignment_keeps_current_task_and_bounded_newest_verified_rd_references(
    tmp_path, automatic
):
    kr, work = assignment()
    kr = kr.model_copy(update={"acceptance_criteria": ("CurrentCriterionNeedle",)})
    work = work.model_copy(update={"task": "CurrentTaskNeedle"})
    async with services_with_provider(
        tmp_path,
        lambda *_: {"content": "unused"},
        limits=UNLIMITED.model_dump(mode="json") if automatic else None,
    ) as (services, *_):
        reports = await seed_consultations(services, kr)
        host = services._planning_host(
            "engineering_head", kr, payload={"work": work.model_dump(mode="json")}
        )
        artifact = await services._record_agent_assignment(work, kr, host)
        _, raw = await services.artifacts.read(artifact["artifact_id"], limit=None)
        proof = json.loads(raw)
        if automatic:
            assert "CurrentTaskNeedle" in raw[:12000] and "CurrentCriterionNeedle" in raw[:12000]
            assert proof["rd_consultation_coverage"] == {
                "total": 12,
                "included": 8,
                "omitted": 4,
                "has_more": True,
                "order": "newest_first",
            }
            selected = proof["rd_consultations"]
            assert [item["consultation_artifact_id"] for item in selected] == [
                item[1]["artifact_id"] for item in reversed(reports[-8:])
            ]
            assert all(
                len(item["artifact_ids"]) == 8
                and item["artifact_count"] == 10
                and item["artifacts_omitted"] == 2
                and item["artifacts_has_more"]
                for item in selected
            )
            assert all(item["report_artifact_id"] in item["artifact_ids"] for item in selected)
            assert len(raw) < 12000
        else:
            assert len(proof["rd_consultations"]) == 12 and "rd_consultation_coverage" not in proof


async def test_selected_recent_rd_provenance_still_validates_immutable_report_bytes(tmp_path):
    kr, _ = assignment()
    async with services_with_provider(
        tmp_path, lambda *_: {"content": "unused"}, limits=UNLIMITED.model_dump(mode="json")
    ) as (services, *_):
        reports = await seed_consultations(services, kr)
        Path(reports[-1][0]["path"]).write_text("Tampered report")
        with pytest.raises(EscalationSignal, match="delegation evidence failed validation"):
            await services._verified_rd_provenance(kr)
