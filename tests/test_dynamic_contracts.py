import httpx
import pytest
from pydantic import ValidationError

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import (
    EngineeringSpecialistSpec,
    TaskSpecialistSpec,
    WorkPackage,
    worker_agent_id,
    worker_agent_metadata,
)
from org_harness.storage import MemoryStorage


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_model_deadlines_must_be_finite(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, model_timeout=value)


def package():
    return WorkPackage(
        work_package_id="frontend",
        kr_id="website",
        role="backend_coder",
        task="Build the scene",
        acceptance_criteria=("Render the requested scene",),
        specialist=EngineeringSpecialistSpec(
            name="Three.js specialist",
            instructions="Implement and verify the scene.",
            tools=("write_file", "run_command", "publish_file"),
        ),
    )


def test_specialist_identity_is_stable_bounded_and_isolated_from_other_missions():
    work = package()
    identity = worker_agent_id("92a0129d-decd-4c63-b8b9-9ec1fbf0d4cc", work)
    assert identity == "specialist:92a0129d-decd-4c63-b8b9-9ec1fbf0d4cc:f251cff817aadd08"
    assert len(identity) <= 100
    assert (
        worker_agent_id(
            "92a0129d-decd-4c63-b8b9-9ec1fbf0d4cc",
            WorkPackage.model_validate_json(work.model_dump_json()),
        )
        == identity
    )
    assert worker_agent_id("another-mission", work) != identity
    assert worker_agent_id("a" * 200, work) != identity
    assert len(worker_agent_id("a" * 200, work)) <= 100
    assert (
        worker_agent_id(
            "92a0129d-decd-4c63-b8b9-9ec1fbf0d4cc", work.model_copy(update={"execution_attempt": 1})
        )
        == identity
    )


@pytest.mark.parametrize(
    ("role", "tool"),
    [
        ("market_researcher", "run_command"),
        ("market_researcher", "validate_code_syntax"),
        ("market_researcher", "run_mission_tool"),
        ("backend_coder", "search_market_data"),
        ("system_architect", "search_market_data"),
    ],
)
def test_named_specialists_cannot_expand_their_inherited_role_capabilities(role, tool):
    data = package().model_dump(mode="json")
    data["role"] = role
    data["specialist"]["tools"] = [tool]
    with pytest.raises(ValidationError, match="inherited worker role"):
        WorkPackage.model_validate(data)


def test_named_data_analyst_can_reuse_tested_mission_tools_within_its_command_capabilities():
    data = package().model_dump(mode="json")
    data["role"] = "data_analyst"
    data["specialist"]["tools"] = ["run_mission_tool"]
    work = WorkPackage.model_validate(data)
    assert work.role == "data_analyst" and work.specialist.tools == ("run_mission_tool",)


def test_research_specialist_roundtrip_has_research_parent_without_changing_legacy_fields():
    data = package().model_dump(mode="json")
    data["role"] = "market_researcher"
    data["specialist"] = {
        "name": "bioRxiv Content Cartographer",
        "instructions": "Map the paper's claims to source evidence.",
        "tools": ["search_market_data", "read_web_page"],
    }
    work = WorkPackage.model_validate(data)
    assert isinstance(work.specialist, TaskSpecialistSpec)
    assert EngineeringSpecialistSpec is TaskSpecialistSpec
    assert WorkPackage.model_validate_json(work.model_dump_json()) == work
    assert worker_agent_metadata(work) == {
        "display_name": "bioRxiv Content Cartographer",
        "agent_type": "research_specialist",
        "parent_agent_id": "research_head",
        "department": "research",
        "model_parent": "market_researcher",
        "base_role": "market_researcher",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"instructions": "\n"},
        {"tools": ("consult_tools_rd",)},
        {"tools": ("read_file", "read_file")},
    ],
)
def test_specialist_contract_rejects_empty_definitions_or_delegation_capabilities(changes):
    with pytest.raises(ValidationError):
        EngineeringSpecialistSpec.model_validate(
            {
                "name": "Task specialist",
                "instructions": "Complete the assignment",
                **changes,
            }
        )


async def test_rd_model_override_is_configurable_and_snapshotted(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, openai_api_key="test-key")
    storage = MemoryStorage()
    app = create_app(settings, storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        selection = {"provider": "configured", "model": "rd-model", "reasoning_effort": "low"}
        response = await client.put("/api/settings/agents/tools_rd_lead", json=selection)
        assert response.status_code == 200
        response = await client.post("/api/runs", json={"user_request": "Build a website"})
        assert response.status_code == 202
        run = await storage.get_run(response.json()["run_id"])
        assert run["agent_model_configs"]["tools_rd_lead"] == selection
        assert (
            await client.put("/api/settings/agents/specialist:forged", json=selection)
        ).status_code == 422
        assert "test-key" not in (await client.get("/api/settings")).text
        await client.delete("/api/settings/agents/tools_rd_lead")
        assert (await storage.get_run(run["run_id"]))["agent_model_configs"][
            "tools_rd_lead"
        ] == selection
