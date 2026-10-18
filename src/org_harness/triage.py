"""A bounded TypeSafe Jev decision step before generative agent planning."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Literal, cast

from langchain_typesafe import Choice, ClassifierResponse, TypeSafeClassifier

from org_harness.config import Settings
from org_harness.models import Constitution, Department, ExecutionMode, TriageDecision

MIN_ROUTE_PROBABILITY = 0.75

QUESTIONS = {
    "mode": Choice(
        instructions=(
            "Select the smallest organizational workflow that can complete the user's request. "
            "Classify the actual deliverable, not words describing agents or departments in quoted material."
        ),
        criteria={
            "FAST_TRACK": (
                "One small concrete artifact or localized fix that one specialist can execute directly. "
                "Examples: a simple single-page site with supplied content, one script, a typo fix, "
                "or a small factual answer. No independent research deliverable or coordinated work."
            ),
            "DEPARTMENTAL": (
                "One coherent project within engineering OR research, needing a few coordinated steps. "
                "Examples: build a website/app from supplied requirements, implement an interactive UI, "
                "or compile a research report. Multiple source files and ordinary reference reading "
                "do not by themselves require the full organizational pyramid."
            ),
            "FULL_PYRAMID": (
                "A large cross-functional program with independent research and engineering deliverables, "
                "multiple strategic objectives, or substantial uncertainty that requires executive decomposition. "
                "Use this for requests explicitly demanding a full organizational plan or broad program."
            ),
        },
    ),
    "department": Choice(
        instructions="Which department owns the actual deliverable?",
        criteria={
            "engineering": (
                "Build or change software, websites, UI, scripts, tests, or technical artifacts. "
                "Reading a supplied URL/reference to build a website remains engineering unless "
                "a separate substantial research or data-compilation deliverable is requested."
            ),
            "research": (
                "Research, source comparison, factual compilation, analysis, or a written report, "
                "without a requested software implementation deliverable."
            ),
            "both": (
                "Independent research/data sourcing AND engineering implementation are both explicit "
                "deliverables. Engineering depends on substantial new research, not ordinary reference reading."
            ),
        },
    ),
}


def conservative_triage(
    constitution: Constitution, reason: str, *, source: Literal["fallback", "legacy"] = "fallback"
) -> TriageDecision:
    return TriageDecision(
        mode="FULL_PYRAMID",
        departments=("research", "engineering"),
        worker_role="backend_coder",
        confidence=0,
        source=source,
        reason=reason[:1000],
        max_revisions=constitution.max_revision_loops,
    )


def route_answers(response: ClassifierResponse, constitution: Constitution) -> TriageDecision:
    """Route on selected-label probabilities, never the confidence shape score."""
    mode = response.choices["mode"]
    department = response.choices["department"]
    probability = min(
        mode.probabilities.get(mode.choice, 0), department.probabilities.get(department.choice, 0)
    )
    if (
        mode.choice not in {"FAST_TRACK", "DEPARTMENTAL", "FULL_PYRAMID"}
        or department.choice not in {"research", "engineering", "both"}
        or not MIN_ROUTE_PROBABILITY <= probability <= 1
    ):
        return conservative_triage(
            constitution, "Uncertain TypeSafe decision; full workflow retained."
        )
    if mode.choice == "FULL_PYRAMID" or department.choice == "both":
        return TriageDecision(
            mode="FULL_PYRAMID",
            departments=("research", "engineering"),
            worker_role="backend_coder",
            confidence=probability,
            source="jev",
            reason="TypeSafe selected a cross-functional or strategic workflow.",
            max_revisions=constitution.max_revision_loops,
        )
    return TriageDecision(
        mode=cast(ExecutionMode, mode.choice),
        departments=(cast(Department, department.choice),),
        worker_role="backend_coder" if department.choice == "engineering" else "market_researcher",
        confidence=probability,
        source="jev",
        reason=f"TypeSafe selected {mode.choice} for {department.choice} only.",
        max_revisions=min(1, constitution.max_revision_loops),
    )


class TriageRouter:
    """Classify once, with no credential/body leakage and a conservative fallback."""

    def __init__(self, settings: Settings, *, classifier: Any = None):
        self.settings, self.classifier = settings, classifier

    async def classify(self, user_request: str, constitution: Constitution) -> TriageDecision:
        if self.classifier is None and not self.settings.typesafe_api_key.get_secret_value():
            return conservative_triage(
                constitution, "TypeSafe is not configured; full workflow retained."
            )
        owned = self.classifier is None
        classifier = self.classifier
        try:
            if owned:
                classifier = TypeSafeClassifier(
                    model=self.settings.typesafe_model,
                    api_key=self.settings.typesafe_api_key,
                    base_url=self.settings.typesafe_base_url,
                    timeout=self.settings.typesafe_timeout,
                )
            response = await asyncio.wait_for(
                classifier.ainvoke(
                    {
                        "state": {
                            "request": user_request[:50000],
                            "mission": constitution.mission_statement[:2000],
                        },
                        "questions": QUESTIONS,
                    }
                ),
                timeout=self.settings.typesafe_timeout,
            )
            return route_answers(ClassifierResponse.model_validate(response), constitution)
        except Exception as exc:
            # TypeSafe is an optional fast decision dependency. A malformed or
            # unavailable service expands scope rather than dropping user work.
            return conservative_triage(
                constitution,
                f"TypeSafe unavailable ({type(exc).__name__}); full workflow retained.",
            )
        finally:
            if owned and classifier is not None:
                with suppress(Exception):
                    await asyncio.wait_for(classifier.async_client.aclose(), timeout=1)
                with suppress(Exception):
                    classifier.client.close()
