import httpx
import pytest
from pydantic import ValidationError

from org_harness.api import create_app
from org_harness.config import Settings
from org_harness.models import EngineeringSpecialistSpec, WorkPackage, worker_agent_id
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
    assert identity.startswith("specialist:92a0129d-decd-4c63-b8b9-9ec1fbf0d4cc:")
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
