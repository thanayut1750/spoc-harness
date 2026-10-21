import asyncio
import time

import httpx2
import pytest
from langchain_typesafe import ClassifierResponse, TypeSafeClassifier
from langchain_typesafe.client import TypeSafeAPIConnectionError

from org_harness.config import Settings
from org_harness.models import Constitution
from org_harness.triage import TriageRouter, route_answers


def answers(mode="FAST_TRACK", department="engineering", probability=0.95, confidence=0.9):
    return ClassifierResponse(
        model="jev-1.13.0",
        answers={
            "mode": {
                "type": "choice",
                "choice": mode,
                "probabilities": {mode: probability},
                "confidence": confidence,
            },
            "department": {
                "type": "choice",
                "choice": department,
                "probabilities": {department: probability},
                "confidence": confidence,
            },
        },
    )


@pytest.mark.parametrize(
    "mode,department,expected_departments",
    [
        ("FAST_TRACK", "engineering", ("engineering",)),
        ("DEPARTMENTAL", "research", ("research",)),
        ("FULL_PYRAMID", "engineering", ("research", "engineering")),
        ("FAST_TRACK", "both", ("research", "engineering")),
    ],
)
def test_typed_probabilities_choose_required_workflow(mode, department, expected_departments):
    result = route_answers(answers(mode, department), Constitution())
    assert result.departments == expected_departments
    assert result.mode == ("FULL_PYRAMID" if len(expected_departments) == 2 else mode)
    assert result.max_revisions == (2 if result.mode == "FULL_PYRAMID" else 1)
    assert result.worker_role == (
        "market_researcher" if department == "research" else "backend_coder"
    )


def test_route_uses_selected_probability_not_confidence_shape():
    assert (
        route_answers(answers(probability=0.99, confidence=0.01), Constitution()).mode
        == "FAST_TRACK"
    )
    uncertain = route_answers(answers(probability=0.6, confidence=0.99), Constitution())
    assert uncertain.mode == "FULL_PYRAMID"
    assert uncertain.source == "fallback"


async def test_missing_key_falls_back_without_calling_provider():
    result = await TriageRouter(Settings(_env_file=None, typesafe_api_key="")).classify(
        "Build site", Constitution()
    )
    assert result.mode == "FULL_PYRAMID"
    assert result.source == "fallback"


async def test_questions_are_batched_and_typed_in_one_provider_request():
    requests = []

    class Classifier:
        async def ainvoke(self, request):
            requests.append(request)
            return answers("DEPARTMENTAL")

    router = TriageRouter(Settings(_env_file=None), classifier=Classifier())
    result = await router.classify("Build a three.js website", Constitution())
    assert result.mode == "DEPARTMENTAL"
    assert len(requests) == 1
    assert set(requests[0]["questions"]) == {"mode", "department"}
    assert requests[0]["state"]["request"] == "Build a three.js website"


async def test_unavailable_classifier_is_bounded_and_never_leaks_secret_errors():
    class SlowClassifier:
        async def ainvoke(self, request):
            await asyncio.sleep(1)

    router = TriageRouter(
        Settings(_env_file=None, typesafe_timeout=0.01), classifier=SlowClassifier()
    )
    started = time.monotonic()
    result = await router.classify("Build site", Constitution())
    assert time.monotonic() - started < 0.5
    assert result.mode == "FULL_PYRAMID"
    assert result.source == "fallback"

    class BrokenClassifier:
        async def ainvoke(self, request):
            raise TypeSafeAPIConnectionError("Secret API key must never appear")

    result = await TriageRouter(Settings(_env_file=None), classifier=BrokenClassifier()).classify(
        "Build site", Constitution()
    )
    assert "Secret API" not in result.reason
    assert "TypeSafeAPIConnectionError" in result.reason


async def test_missing_routing_choice_is_provider_validation_failure_with_fallback():
    class IncompleteClassifier:
        async def ainvoke(self, request):
            return answers().model_copy(update={"answers": {}})

    result = await TriageRouter(
        Settings(_env_file=None), classifier=IncompleteClassifier()
    ).classify("Build site", Constitution())
    assert result.mode == "FULL_PYRAMID"
    assert result.source == "fallback"
    assert "ValueError" in result.reason


@pytest.mark.parametrize("error_type", [KeyError, RuntimeError, OSError])
async def test_classifier_programming_and_infrastructure_errors_are_not_hidden(error_type):
    class BrokenClassifier:
        async def ainvoke(self, request):
            raise error_type("Unexpected failure")

    with pytest.raises(error_type):
        await TriageRouter(Settings(_env_file=None), classifier=BrokenClassifier()).classify(
            "Build site", Constitution()
        )


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_native_typesafe_sdk_auth_rate_limit_and_service_failure_fall_back_safely(status):
    def response(request):
        return httpx2.Response(status, json={"error": "private provider body"}, request=request)

    with httpx2.Client(transport=httpx2.MockTransport(response)) as sync_client:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(response)) as async_client:
            classifier = TypeSafeClassifier(
                api_key="synthetic-test-key", client=sync_client, async_client=async_client
            )
            result = await TriageRouter(Settings(_env_file=None), classifier=classifier).classify(
                "Build a site", Constitution()
            )
    assert result.mode == "FULL_PYRAMID"
    assert result.source == "fallback"
    assert "TypeSafe" in result.reason
    assert "private provider body" not in result.reason
    assert "synthetic-test-key" not in result.reason


async def test_cancellation_is_not_swallowed_as_classification_fallback():
    class CancelledClassifier:
        async def ainvoke(self, request):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await TriageRouter(Settings(_env_file=None), classifier=CancelledClassifier()).classify(
            "Build site", Constitution()
        )
