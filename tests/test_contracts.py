import pytest
from pydantic import ValidationError

from org_harness.config import Settings
from org_harness.models import Constitution, Evaluation, KeyResult


def test_constitution_is_deeply_immutable_and_serializable():
    policy = Constitution(prohibited_actions=["publish secrets"])
    assert isinstance(policy.prohibited_actions, tuple)
    assert Constitution.model_validate_json(policy.model_dump_json()) == policy
    with pytest.raises(ValidationError):
        policy.mission_statement = "changed"


def test_key_result_and_score_validation():
    with pytest.raises(ValidationError):
        KeyResult(
            kr_id="r1", description="Research", acceptance_criteria=[], target_department="research"
        )
    with pytest.raises(ValidationError):
        Evaluation(
            passed_constitution=True,
            passed_kr_criteria=True,
            score=1.2,
            feedback="",
            recommended_action="approve",
        )


def test_settings_alias_and_environment_precedence(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("MAIN_MODEL=file-model\nREASIONING_EFFORT=max\n")
    monkeypatch.setenv("MAIN_MODEL", "process-model")
    settings = Settings(_env_file=env)
    assert settings.main_model == "process-model"
    assert settings.reasoning_effort == "max"
    monkeypatch.setenv("REASONING_EFFORT", "low")
    assert Settings(_env_file=env).reasoning_effort == "low"


def test_settings_do_not_display_secrets():
    settings = Settings(_env_file=None, openai_api_key="private-value")
    assert "private-value" not in str(settings)
    assert "private-value" not in str(settings.redacted())
