"""Explicit unlimited-mode policy and cooperative durable work boundaries."""

from collections.abc import Mapping
from typing import Any

CALL_CAPS = ("max_model_calls", "worker_model_calls", "max_tool_calls")
AGENT_CHUNK_TURNS = 32


def autonomous_mode(limits: Any) -> bool:
    """Only three explicit unlimited caps opt a mission into autonomous execution.

    Missing fields are legacy finite defaults, never implied consent to unlimited
    execution. Read this from the current mission, not an old graph checkpoint.
    """
    if hasattr(limits, "model_dump"):
        limits = limits.model_dump()
    return isinstance(limits, Mapping) and all(
        key in limits and limits[key] is None for key in CALL_CAPS
    )


def retry_delay(attempt: int) -> float:
    """Persistent cooldowns avoid spinning or hammering unavailable providers."""
    return float(min(300, 5 * 2 ** min(max(attempt - 1, 0), 6)))


class AutonomousCheckpointYield(Exception):
    """A healthy private agent chunk yielded with its next step checkpointed.

    This must escape ordinary escalation handling so the same work/epoch and
    private checkpoint resume, rather than creating a new assignment or review.
    """

    def __init__(self, reason: str, delay_seconds: float = 0, *, recoverable_failure: bool = False):
        self.reason = reason
        self.delay_seconds = delay_seconds
        self.recoverable_failure = recoverable_failure
        super().__init__(reason)
