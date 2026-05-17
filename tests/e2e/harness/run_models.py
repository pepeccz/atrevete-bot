"""Run-scoped models for conversational QA harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.e2e.harness.redis_harness import (
        ClassifierOutput,
        MilestoneTracker,
        RedisTestHarness,
        ReplyGenerator,
        ResponseClassifier,
    )


@dataclass(slots=True)
class QARunIdentity:
    """Unique identifiers for an isolated QA conversation run."""

    conversation_id: str
    customer_phone: str
    sender_name: str
    run_started_at: datetime


@dataclass(slots=True)
class TurnEvidence:
    """Normalized evidence envelope for a single conversational turn."""

    turn_number: int
    user_message: str
    agent_response: str | None
    response_latency_ms: int
    timed_out: bool
    raw_payloads: list[dict[str, Any]]
    timestamp_sent: datetime
    timestamp_received: datetime | None
    tool_evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class QARunSession:
    """Aggregates identity, timers, and evidence for one QA run."""

    identity: QARunIdentity
    started_monotonic: float
    batch_window_seconds: float = 3.0
    turn_count: int = 0
    total_duration_ms: int = 0
    raw_payloads: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[TurnEvidence] = field(default_factory=list)


@dataclass(slots=True)
class LLMTurnResponse:
    """Structured output from LLM per turn (replaces ResponseClassifier + ReplyGenerator + MilestoneTracker)."""

    reply: str  # The customer's next message
    should_stop: bool  # Whether conversation should terminate
    stop_reason: str  # 'booking_complete' | 'escalated' | 'dead_loop' | 'timeout' | 'indecisive' | 'other'
    confidence: float  # 0.0-1.0 confidence in this decision
    bugs: list[dict[str, Any]] = field(default_factory=list)  # Semantic bugs detected (e.g., bot re-asked already-answered Q)
    milestone_reached: str | None = None  # Which milestone reached (e.g., 'appointment_confirmed')
    flow_status: str = "in_progress"  # 'in_progress' | 'complete' | 'escalated'
    reasoning_trace: str = ""  # Why the LLM made this decision (for debug)


@dataclass(slots=True)
class TurnRecord:
    """Adaptive turn trace with evidence and classification."""

    message: str
    evidence: TurnEvidence
    classification: ClassifierOutput
    bugs: list[dict[str, Any]] = field(default_factory=list)
    final_state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConversationResult:
    """Adaptive QA result returned to evaluators and assertions."""

    turns: list[TurnRecord]
    outcome: str
    milestone_reached: str
    final_state: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    termination_reason: str = ""
    total_duration_ms: int = 0
    bugs_summary: str = ""


@dataclass(slots=True)
class AdaptiveHarness:
    """Fixture-friendly bundle for adaptive QA runs."""

    session: QARunSession
    classifier: ResponseClassifier
    reply_gen: ReplyGenerator
    tracker: MilestoneTracker
    redis: RedisTestHarness
    db_cleaner: Any | None = None
