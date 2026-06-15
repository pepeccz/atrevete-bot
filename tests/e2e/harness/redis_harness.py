"""Redis-based harness for conversational QA flows."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis

from shared.config import get_settings
from shared.redis_client import INCOMING_STREAM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from tests.e2e.harness.run_models import QARunIdentity, QARunSession


# =============================================================================
# Simple value objects
# =============================================================================


@dataclass(slots=True)
class ClassifierOutput:
    """Output from ResponseClassifier.classify()."""

    intent: str
    confidence: float
    booking_step: str = ""
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class ToolCallEvidence:
    """Single tool call recorded during a QA turn."""

    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    source: str  # "checkpoint" | "stream"
    timestamp: datetime


# =============================================================================
# RunTerminated exception
# =============================================================================


class RunTerminated(Exception):
    """Raised by MilestoneTracker when a terminal condition is reached."""

    def __init__(self, outcome: str, reason: str):
        super().__init__(reason)
        self.outcome = outcome
        self.outcome_reason = reason


# =============================================================================
# Tool trace validation
# =============================================================================

_BOOKING_FLOW_TOOLS = ["check_availability", "book_appointment"]

# Map canonical tool aliases to a canonical name for validation
# Note: search_services was removed in catalog-in-prompt architecture (Domain E)
_CANONICAL_TOOL = {
    "find_next_available": "check_availability",
    "check_availability": "check_availability",
    "book": "book_appointment",
    "book_appointment": "book_appointment",
}


@dataclass(slots=True)
class ToolTraceReport:
    """Result of validate_tool_trace()."""

    all_required_present: bool
    missing_tools: list[str]
    out_of_order: list[str]
    found_tools: list[str]


def validate_tool_trace(evidence: list[ToolCallEvidence], flow_type: str) -> ToolTraceReport:
    """Validate that a booking flow has the required tools in the right order."""
    if flow_type != "booking":
        return ToolTraceReport(
            all_required_present=True,
            missing_tools=[],
            out_of_order=[],
            found_tools=[],
        )

    # Normalize tool names
    found: list[str] = []
    for entry in evidence:
        canonical = _CANONICAL_TOOL.get(entry.tool_name)
        if canonical and canonical not in found:
            found.append(canonical)

    missing = [t for t in _BOOKING_FLOW_TOOLS if t not in found]

    # Check order: must appear in the same order as _BOOKING_FLOW_TOOLS
    out_of_order: list[str] = []
    if not missing:
        expected_order = [t for t in _BOOKING_FLOW_TOOLS if t in found]
        if found != expected_order:
            out_of_order = found

    all_present = len(missing) == 0 and len(out_of_order) == 0

    return ToolTraceReport(
        all_required_present=all_present,
        missing_tools=missing,
        out_of_order=out_of_order,
        found_tools=found,
    )


# =============================================================================
# Tool evidence adapters
# =============================================================================


class CheckpointToolEvidenceAdapter:
    """Collects tool call evidence from LangGraph checkpoint state."""

    def __init__(self, harness: RedisTestHarness):
        self._harness = harness

    async def collect(self, conversation_id: str, turn_index: int) -> list[ToolCallEvidence]:
        """Return tool evidence for a specific turn from the checkpoint."""
        state = await self._harness.capture_final_state(conversation_id)
        if state is None:
            return []

        raw_trace = state.get("qa_tool_trace", [])
        result = []
        for entry in raw_trace:
            if entry.get("turn_index") == turn_index:
                ts_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    ts = datetime.now(UTC)
                result.append(
                    ToolCallEvidence(
                        tool_name=entry.get("tool_name", ""),
                        arguments=dict(entry.get("arguments") or {}),
                        result=dict(entry.get("result") or {}),
                        source=entry.get("source", "checkpoint"),
                        timestamp=ts,
                    )
                )
        return result


class StreamToolEvidenceAdapter:
    """Collects tool call evidence from a Redis Stream."""

    STREAM_KEY_TEMPLATE = "qa_tool_trace:{conversation_id}"

    def __init__(self, harness: RedisTestHarness):
        self._harness = harness

    async def collect(self, conversation_id: str, turn_index: int) -> list[ToolCallEvidence]:
        """Return tool evidence for a specific turn from the stream."""
        stream_key = self.STREAM_KEY_TEMPLATE.format(conversation_id=conversation_id)
        raw = await self._harness.redis.xrange(stream_key, "-", "+")
        result = []
        for stream_id, fields in raw:
            # stream_id is bytes like b"1742385600000-0"
            stream_id_str = stream_id.decode("utf-8") if isinstance(stream_id, bytes) else stream_id
            # Extract ms timestamp from stream ID (format: <ms>-<seq>)
            ms_part = stream_id_str.split("-")[0]
            try:
                ts = datetime.fromtimestamp(int(ms_part) / 1000, tz=UTC)
            except (ValueError, TypeError):
                ts = datetime.now(UTC)

            def decode(v: bytes | str) -> str:
                return v.decode("utf-8") if isinstance(v, bytes) else v

            entry_turn = int(
                decode(fields.get(b"turn_index", b"0") or fields.get("turn_index", "0"))
            )
            if entry_turn != turn_index:
                continue

            tool_name_raw = fields.get(b"tool_name", b"") or fields.get("tool_name", "")
            args_raw = fields.get(b"args", b"{}") or fields.get("args", "{}")
            result_raw = fields.get(b"result", b"{}") or fields.get("result", "{}")
            source_raw = fields.get(b"source", b"stream") or fields.get("source", "stream")

            try:
                arguments = json.loads(decode(args_raw))
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            try:
                result_data = json.loads(decode(result_raw))
            except (json.JSONDecodeError, TypeError):
                result_data = {}

            result.append(
                ToolCallEvidence(
                    tool_name=decode(tool_name_raw),
                    arguments=arguments,
                    result=result_data,
                    source=decode(source_raw),
                    timestamp=ts,
                )
            )
        return result


class ConversationTurnAdapter:
    """Reads tool_calls JSONB from conversation_turns table (post-flush, 3rd tier).

    Used as a fallback when both CheckpointToolEvidenceAdapter and
    StreamToolEvidenceAdapter return empty (e.g. Redis evicted, checkpoint
    TTL expired, Langfuse unavailable). Reads from the PostgreSQL
    conversation_turns table which persists tool call summaries permanently.

    source="db_turns" in returned ToolCallEvidence items indicates this path.
    """

    def __init__(self, harness: RedisTestHarness) -> None:
        self._harness = harness
        # Optional override for testing (inject engine directly without settings)
        self._engine: AsyncEngine | None = None

    async def _fetch_turn_row(
        self, conversation_id: str, turn_index: int
    ) -> tuple[list[dict[str, Any]], datetime] | None:
        """Query conversation_turns for the given conversation_id and turn_number.

        Returns (tool_calls, created_at) or None if no matching row found.
        """
        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            if self._engine is not None:
                engine = self._engine
                should_dispose = False
            else:
                settings = get_settings()
                engine = create_async_engine(settings.DATABASE_URL, echo=False)
                should_dispose = True

            try:
                async with engine.connect() as conn:
                    result = await conn.execute(
                        text("""
                            SELECT ct.tool_calls, ct.created_at
                            FROM conversation_turns ct
                            JOIN conversation_history ch
                              ON ch.id = ct.conversation_history_id
                            WHERE ch.conversation_id = :conv_id
                              AND ct.turn_number = :turn_number
                            LIMIT 1
                            """),
                        {"conv_id": conversation_id, "turn_number": turn_index},
                    )
                    row = result.fetchone()
                    if row is None:
                        return None
                    tool_calls_raw, created_at = row
                    if not tool_calls_raw:
                        return None
                    # JSONB may come back as a list already or as a JSON string
                    if isinstance(tool_calls_raw, str):
                        tool_calls: list[dict[str, Any]] = json.loads(tool_calls_raw)
                    else:
                        tool_calls = list(tool_calls_raw)
                    return tool_calls, created_at
            finally:
                if should_dispose:
                    await engine.dispose()
        except Exception:
            return None

    async def collect(self, conversation_id: str, turn_index: int) -> list[ToolCallEvidence]:
        """Return tool evidence for a specific turn from conversation_turns DB table.

        Returns ToolCallEvidence items with source='db_turns'.
        """
        row = await self._fetch_turn_row(conversation_id, turn_index)
        if row is None:
            return []

        tool_calls, created_at = row
        result: list[ToolCallEvidence] = []
        for entry in tool_calls:
            tool_name = entry.get("name", "")
            args = entry.get("args", {}) or {}
            result_summary = entry.get("result_summary", "")
            # Change N (W8): crashed tool calls carry status "error" / "missing"
            call_status = entry.get("status", "")

            # Normalise timestamp: created_at from DB is timezone-aware if TIMESTAMP(tz=True)
            if created_at is not None and hasattr(created_at, "astimezone"):
                ts = created_at.astimezone(UTC)
            elif created_at is not None:
                ts = datetime.fromtimestamp(created_at, tz=UTC)
            else:
                ts = datetime.now(UTC)

            result_payload: dict[str, Any] = {}
            if result_summary:
                result_payload["result_summary"] = result_summary
            if call_status:
                result_payload["status"] = call_status

            result.append(
                ToolCallEvidence(
                    tool_name=tool_name,
                    arguments=dict(args) if isinstance(args, dict) else {},
                    result=result_payload,
                    source="db_turns",
                    timestamp=ts,
                )
            )
        return result


# =============================================================================
# Adaptive persona classifier / reply generator / milestone tracker
# =============================================================================


class ResponseClassifier:
    """Keyword + checkpoint-aware classifier for bot responses."""

    # Intent → keywords mapping
    _KEYWORD_MAP: dict[str, list[str]] = {
        "booking": ["reservar", "turno", "cita", "agendar"],
        "slot": ["horario", "turno", "disponible", "jueves", "lunes", "martes", "miércoles"],
        "stylist": ["estilista", "luciana", "sofi", "cualquiera", "Luciana"],
        "service": ["servicio", "corte", "dama", "caballero", "manicura"],
        "confirmation": ["confirmo", "confirmado", "confirmar", "resumen"],
        "cancellation": ["cancelar", "anular", "no puedo"],
        "escalation": ["humano", "persona", "equipo", "derivar"],
        "clarification": ["hola", "bienvenida", "qué", "cuál", "podés", "querés", "dama"],
        "notes": ["comentario", "nota", "aclaración"],
        "completion": ["agendado", "reservado", "confirmado"],
    }

    def __init__(self, checkpoint_state: dict[str, Any] | None = None):
        self._checkpoint_state = checkpoint_state or {}

    def classify(
        self,
        bot_response: str,
        milestone: Milestone,
        persona: Any,
    ) -> ClassifierOutput:
        """Classify bot response against a milestone."""
        lower = bot_response.lower()

        # Find matching keywords from expected_keywords list
        matched: list[str] = []
        for kw in milestone.expected_keywords:
            if kw.lower() in lower:
                matched.append(kw)

        # Also check global keyword map for the milestone's intent classifier
        intent = milestone.intent_classifier
        for kw in self._KEYWORD_MAP.get(intent, []):
            if kw.lower() in lower and kw not in matched:
                matched.append(kw)

        # Determine confidence
        if matched:
            confidence = min(0.3 + 0.15 * len(matched), 1.0)
        else:
            # Fallback: intent is forced to the milestone's classifier with low confidence
            confidence = 0.35

        # Extract booking_step from checkpoint state if present
        booking_step = ""
        if self._checkpoint_state:
            mc = self._checkpoint_state.get("mode_context", {})
            if isinstance(mc, dict):
                booking_step = mc.get("booking_step", "")

        return ClassifierOutput(
            intent=intent,
            confidence=confidence,
            booking_step=booking_step,
            matched_keywords=tuple(matched),
        )


class ReplyGenerator:
    """Deterministic reply generator driven by persona preferences."""

    _DEFAULT_TEMPLATES: dict[str, str] = {
        "booking": "{service}",
        "slot": "{date} {time}",
        "stylist": "{stylist}",
        "service": "{service_variant}",
        "confirmation": "sí",
        "cancellation": "cancelar",
        "escalation": "quiero hablar con alguien",
        "clarification": "{service_variant}",
        "notes": "{notes}",
        "completion": "gracias",
    }

    def __init__(self, reply_templates: dict[str, str] | None = None):
        self._templates = {**self._DEFAULT_TEMPLATES, **(reply_templates or {})}

    def generate_reply(
        self,
        persona_goals: dict[str, Any],
        persona_preferences: Any,
        last_classifier_output: ClassifierOutput,
        conversation_history: list[str],
    ) -> str:
        """Generate deterministic reply for the given intent."""
        intent = last_classifier_output.intent
        template = self._templates.get(intent, "{service}")

        # Build substitution context from persona_goals
        context: dict[str, str] = {}
        for key, val in persona_goals.items():
            context[key] = str(val) if val is not None else ""

        # Apply template
        try:
            reply = template.format_map(context)
        except KeyError:
            reply = template

        # Truncate to 200 chars with ellipsis
        if len(reply) > 200:
            reply = reply[:197] + "..."

        return reply


@dataclass
class Milestone:
    """A single milestone in an adaptive QA flow."""

    name: str
    intent_classifier: str
    expected_keywords: list[str]
    next_milestone: str | None
    fallback_milestone: str | None
    description: str = ""


class MilestoneTracker:
    """Tracks milestone progression and detects terminal conditions."""

    _DEAD_LOOP_THRESHOLD = 3
    _DEAD_LOOP_WINDOW_SECONDS = 30.0

    def __init__(
        self,
        current_milestone: Milestone,
        max_turns: int = 20,
        started_at: datetime | None = None,
    ):
        self.current_milestone = current_milestone
        self.max_turns = max_turns
        self._started_at = started_at or datetime.now(UTC)
        self.turn_count = 0
        self.outcomes_seen: set[str] = set()
        self.outcome_reason: str = ""
        self._consecutive_fallbacks = 0

    def record_turn(
        self,
        classifier_output: ClassifierOutput,
        next_milestone: Milestone | None = None,
        booking_row_exists: bool = False,
    ) -> None:
        """Record a turn and raise RunTerminated if a terminal condition is met."""
        self.turn_count += 1

        intent = classifier_output.intent

        # Check for booking completion
        if self.current_milestone.name in ("completed", "booking_completed") and (
            intent in ("completion", "confirmation") or booking_row_exists
        ):
            reason = f"completed after {self.turn_count} turns"
            self.outcome_reason = reason
            raise RunTerminated("completed", reason)

        # Check for escalation
        if intent == "escalation":
            reason = f"escalation triggered after {self.turn_count} turns"
            self.outcome_reason = reason
            raise RunTerminated("escalation", reason)

        # Check max turns (timeout)
        if self.turn_count > self.max_turns:
            reason = f"timeout after {self.turn_count} turns"
            self.outcome_reason = reason
            raise RunTerminated("timeout", reason)

        # Check dead loop: same fallback intent repeated 3+ times within 30s
        elapsed = (datetime.now(UTC) - self._started_at).total_seconds()
        if intent == "clarification" and elapsed <= self._DEAD_LOOP_WINDOW_SECONDS:
            self._consecutive_fallbacks += 1
            if self._consecutive_fallbacks >= self._DEAD_LOOP_THRESHOLD:
                reason = f"dead loop detected after {self.turn_count} turns"
                self.outcome_reason = reason
                raise RunTerminated("dead_loop", reason)
        else:
            self._consecutive_fallbacks = 0

        # Advance milestone
        if next_milestone is not None:
            self.current_milestone = next_milestone


# =============================================================================
# extract_options
# =============================================================================


def extract_options(text: str, context: str = "stylist") -> list[str]:
    """Extract a list of options from bot text.

    Handles:
    - Numbered lists: "1. Maria\n2. Pedro"
    - Inline comma/or separated: "Maria, Pedro o cualquiera"
    - Multi-word tokens: "Tenemos a Maria, Pedro o cualquiera otro estilista"
    - Includes 'cualquiera' as a valid option
    """
    # Common Spanish words to skip so they are not mistaken for proper nouns
    _SKIP_WORDS = {
        "tenemos", "podés", "elegir", "puede", "atenderte", "querés",
        "perfecto", "ya", "reviso", "eso", "por", "vos", "si", "te",
        "que", "la", "el", "un", "una", "en", "de", "del", "al",
        "con", "para", "por", "sin", "los", "las", "hay", "este",
        "esta", "esto", "ser", "tiene", "tener",
    }

    # Try numbered list first
    numbered_matches = re.findall(r"^\d+\.\s*(.+)$", text, re.MULTILINE)
    if numbered_matches:
        return [m.strip() for m in numbered_matches]

    results: list[str] = []
    seen: set[str] = set()

    # Split on common list separators then scan each segment for candidates
    separators_re = re.compile(r",\s*|\s+o\s+")
    segments = separators_re.split(text)

    for segment in segments:
        # Scan individual words within each segment
        words = re.split(r"\s+", segment.strip())
        for raw_word in words:
            # Strip punctuation
            word = re.sub(r"[.,!?;:]+$", "", raw_word).strip()
            if not word:
                continue
            lower = word.lower()
            if lower == "cualquiera":
                if "cualquiera" not in seen:
                    results.append("cualquiera")
                    seen.add("cualquiera")
            elif (
                re.match(r"^[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñA-ZÁÉÍÓÚÜÑ]+$", word)
                and lower not in _SKIP_WORDS
            ):
                if word not in seen:
                    results.append(word)
                    seen.add(word)

    return results


# =============================================================================
# RedisTestHarness — enhanced
# =============================================================================


class RedisTestHarness:
    """Inject messages into the incoming stream and capture outgoing responses."""

    def __init__(
        self,
        redis_client: redis.Redis,
        binary_redis_client: redis.Redis | None = None,
        response_channel: str = "outgoing_messages",
    ):
        self.redis = redis_client
        self.binary_redis = binary_redis_client
        self.response_channel = response_channel
        self._pubsub: redis.client.PubSub | None = None
        self._owns_binary_client = binary_redis_client is None
        self._turn_counters: dict[str, int] = {}

    def create_session(
        self,
        identity: QARunIdentity,
        batch_window_seconds: float = 3.0,
    ) -> QARunSession:
        """Create a new QA run session bound to this harness."""
        from tests.e2e.harness.run_models import QARunSession

        return QARunSession(
            identity=identity,
            started_monotonic=time.monotonic(),
            batch_window_seconds=batch_window_seconds,
        )

    async def prepare_response_capture(self) -> None:
        if self._pubsub is None:
            self._pubsub = self.redis.pubsub()
            await self._pubsub.subscribe(self.response_channel)

    async def inject_message(
        self,
        conversation_id: str,
        message_text: str,
        customer_phone: str = "+34600000000",
        sender_name: str = "QA Test Client",
        customer_name: str | None = None,
    ) -> str:
        payload = {
            "conversation_id": conversation_id,
            "customer_phone": customer_phone,
            "message_text": message_text,
            "sender_name": sender_name,
            "customer_name": customer_name or sender_name,
            "is_audio_transcription": False,
            "audio_url": None,
        }
        return await self.redis.xadd(INCOMING_STREAM, {"data": json.dumps(payload)})

    async def capture_response(
        self,
        conversation_id: str,
        timeout: float = 30.0,
        batch_window_seconds: float = 3.0,
    ) -> dict[str, Any]:
        """Capture one or more batched responses for a conversation.

        Collects all messages that arrive within batch_window_seconds of the
        first matching message. Returns combined text and raw_payloads list.
        """
        await self.prepare_response_capture()
        assert self._pubsub is not None

        deadline = asyncio.get_running_loop().time() + timeout
        collected_payloads: list[dict[str, Any]] = []
        first_captured_at: datetime | None = None

        while True:
            now = asyncio.get_running_loop().time()
            remaining = deadline - now
            if remaining <= 0 and not collected_payloads:
                raise TimeoutError(
                    f"No response received on '{self.response_channel}' for conversation "
                    f"{conversation_id} within {timeout:.1f}s"
                )

            # If we have at least one payload, check if batch window expired
            if collected_payloads:
                batch_deadline = (
                    asyncio.get_running_loop().time()
                    - (datetime.now(UTC) - first_captured_at).total_seconds()  # type: ignore
                    + batch_window_seconds
                )
                # Simplified: use a short poll window
                poll_timeout = min(batch_window_seconds, max(0.001, remaining))
            else:
                poll_timeout = min(0.1, max(0.001, remaining))

            raw_message = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=poll_timeout
            )

            if raw_message is None:
                # If we already have payloads, batch window exhausted
                if collected_payloads:
                    break
                continue

            raw_data = raw_message.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                continue

            if payload.get("conversation_id") != conversation_id:
                continue

            if first_captured_at is None:
                first_captured_at = datetime.now(UTC)
            collected_payloads.append(payload)

        # Merge messages
        messages = [p.get("message", "") for p in collected_payloads]
        combined_message = "\n\n".join(m for m in messages if m)
        last_payload = collected_payloads[-1] if collected_payloads else {}
        now_dt = datetime.now(UTC)

        return {
            "conversation_id": conversation_id,
            "customer_phone": last_payload.get("customer_phone"),
            "message": combined_message,
            "messages": messages,
            "timestamp_first_captured": first_captured_at or now_dt,
            "timestamp_captured": now_dt,
            "raw_payloads": list(collected_payloads),
            "raw_payload": last_payload,
        }

    async def collect_tool_evidence(
        self, conversation_id: str, turn_index: int
    ) -> list[ToolCallEvidence]:
        """Collect tool call evidence using a 3-tier fallback chain.

        Priority order (returns first non-empty result):
          1. CheckpointToolEvidenceAdapter  — LangGraph checkpoint (in-process, fastest)
          2. StreamToolEvidenceAdapter      — Redis Stream qa_tool_trace:{conv_id}
          3. ConversationTurnAdapter        — PostgreSQL conversation_turns.tool_calls JSONB
                                              (post-flush, survives Redis eviction)

        Returns [] when no evidence is found in any tier (never None).
        source="db_turns" in returned items indicates the DB fallback was used.
        """
        for adapter in (
            CheckpointToolEvidenceAdapter(self),
            StreamToolEvidenceAdapter(self),
            ConversationTurnAdapter(self),
        ):
            try:
                evidence = await adapter.collect(conversation_id, turn_index)
                if evidence:
                    return evidence
            except Exception:
                pass
        return []

    async def execute_turn(
        self,
        user_message: str,
        session: QARunSession,
        timeout: float = 60.0,
        raise_on_timeout: bool = True,
    ) -> dict[str, Any]:
        """Execute a single turn and record evidence in the session."""
        from tests.e2e.harness.run_models import TurnEvidence

        identity = session.identity
        session.turn_count += 1
        turn_number = session.turn_count

        timestamp_sent = datetime.now(UTC)

        # Inject the message
        await self.inject_message(
            conversation_id=identity.conversation_id,
            message_text=user_message,
            customer_phone=identity.customer_phone,
            sender_name=identity.sender_name,
            customer_name=identity.sender_name,
        )

        # Capture response
        timed_out = False
        agent_response: str | None = None
        raw_payloads: list[dict[str, Any]] = []
        timestamp_received: datetime | None = None
        response_latency_ms = 0

        try:
            response = await self.capture_response(
                conversation_id=identity.conversation_id,
                timeout=timeout,
                batch_window_seconds=session.batch_window_seconds,
            )
            timestamp_received = datetime.now(UTC)
            agent_response = response.get("message")
            raw_payloads = response.get("raw_payloads", [])
            latency = (timestamp_received - timestamp_sent).total_seconds() * 1000
            response_latency_ms = int(latency)

            # Record turn in outgoing stream with actual bot reply
            await self.redis.xadd(
                f"qa_outgoing:{identity.conversation_id}",
                {
                    "bot_reply": agent_response or "",
                    "turn_index": str(turn_number),
                    "user_message": user_message,
                },
            )
        except TimeoutError as e:
            if raise_on_timeout:
                raise
            timed_out = True

        # Collect tool evidence
        tool_evidence_list: list[ToolCallEvidence] = []
        try:
            tool_evidence_list = await self.collect_tool_evidence(
                identity.conversation_id, turn_number
            )
        except Exception:
            pass

        tool_evidence_dicts: list[dict[str, Any]] = [
            {
                "tool_name": e.tool_name,
                "arguments": e.arguments,
                "result": e.result,
                "source": e.source,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in tool_evidence_list
        ]

        # Build TurnEvidence
        evidence = TurnEvidence(
            turn_number=turn_number,
            user_message=user_message,
            agent_response=agent_response,
            response_latency_ms=response_latency_ms,
            timed_out=timed_out,
            raw_payloads=raw_payloads,
            timestamp_sent=timestamp_sent,
            timestamp_received=timestamp_received,
            tool_evidence=tool_evidence_dicts,
        )
        session.evidence.append(evidence)
        session.raw_payloads.extend(raw_payloads)

        return {
            "turn_number": turn_number,
            "user_message": user_message,
            "agent_response": agent_response,
            "timestamp_sent": timestamp_sent.isoformat(),
            "timestamp_received": timestamp_received.isoformat() if timestamp_received else None,
            "response_latency_ms": response_latency_ms,
            "timed_out": timed_out,
            "raw_payloads": raw_payloads,
            "tool_evidence": tool_evidence_dicts,
        }

    async def capture_final_state(self, conversation_id: str) -> dict[str, Any] | None:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        client = await self._get_binary_client()
        checkpointer = AsyncRedisSaver(redis_client=client)
        config = {"configurable": {"thread_id": conversation_id}}
        checkpoint = await checkpointer.aget(config)
        if checkpoint is None:
            return None

        if hasattr(checkpoint, "checkpoint"):
            checkpoint_data = checkpoint.checkpoint
        else:
            checkpoint_data = checkpoint

        channel_values = checkpoint_data.get("channel_values", {})
        return dict(channel_values) if isinstance(channel_values, dict) else {"raw": channel_values}

    async def close(self) -> None:
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(self.response_channel)
            await self._pubsub.close()
            self._pubsub = None
        if self._owns_binary_client and self.binary_redis is not None:
            await self.binary_redis.close()
            self.binary_redis = None

    async def _get_binary_client(self) -> redis.Redis:
        if self.binary_redis is None:
            settings = get_settings()
            self.binary_redis = redis.from_url(settings.REDIS_URL, decode_responses=False)
        return self.binary_redis
