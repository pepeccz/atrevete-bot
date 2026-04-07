"""Context loader for conversational QA scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Persona:
    id: str
    name: str
    role: str
    description: str
    behavior: list[str]
    expected_flow: str
    typical_phrases: list[str]


@dataclass(slots=True)
class CheckItem:
    id: str
    description: str


@dataclass(slots=True)
class LevelCriteria:
    id: str
    label: str
    determinism: str
    objective: str
    checks: list[CheckItem]


@dataclass(slots=True)
class FlowStep:
    turn: int
    mode: str
    user: str
    expect: dict[str, Any]


@dataclass(slots=True)
class Flow:
    id: str
    persona_id: str
    description: str
    expected_outcome: str
    steps: list[FlowStep]


@dataclass(slots=True)
class QATestingContext:
    """QA testing context with personas, criteria, and flows.

    Renamed from TestingContext to avoid pytest collection warning
    (pytest tries to collect classes starting with 'Test').
    """

    version: str
    personas: dict[str, Persona]
    criteria: dict[str, LevelCriteria]
    flows: dict[str, Flow]


# =============================================================================
# Adaptive QA structures
# =============================================================================


@dataclass
class Milestone:
    """A single milestone in an adaptive QA flow (re-exported from redis_harness)."""

    name: str
    intent_classifier: str
    expected_keywords: list[str]
    next_milestone: str | None
    fallback_milestone: str | None
    description: str = ""


@dataclass
class AdaptivePreferences:
    """Persona preferences for deterministic reply generation."""

    service: str = ""
    service_variant: str = ""
    stylist: str = ""
    date: str = "esta semana"
    time: str = "mañana"
    notes: str = ""
    add_ons: list[str] = field(default_factory=list)


@dataclass
class AdaptivePersona:
    """Persona with structured preferences for adaptive QA runs."""

    id: str
    name: str
    role: str
    description: str
    behavior: list[str]
    expected_flow: str
    typical_phrases: list[str]
    preferences: AdaptivePreferences = field(default_factory=AdaptivePreferences)


@dataclass
class AdaptiveFlow:
    """Adaptive flow with milestone-based progression."""

    id: str
    persona_id: str
    description: str
    expected_outcome: str
    milestones: list[Milestone] = field(default_factory=list)
    completion_condition: str = ""
    completion_rules: list[str] = field(default_factory=list)


# =============================================================================
# Default adaptive data (in-memory fallback when file lacks adaptive sections)
# =============================================================================

_DEFAULT_ADAPTIVE_PERSONAS: dict[str, dict[str, Any]] = {
    "maria_new_client": {
        "service": "corte de cabello",
        "service_variant": "dama",
        "stylist": "cualquiera",
        "date": "el jueves",
        "time": "por la mañana",
    },
    "carlos_returning_client": {
        "service": "corte de caballero",
        "service_variant": "caballero",
        "stylist": "Luciana",
        "date": "esta semana",
        "time": "mañana",
    },
    "ana_indecisive": {
        "service": "corte",
        "service_variant": "dama",
        "stylist": "cualquiera",
        "date": "cualquier día",
        "time": "mediodía",
    },
    "luis_escalation": {
        "service": "",
        "service_variant": "",
        "stylist": "",
        "date": "",
        "time": "",
    },
    # Aliases used in tests
    "elena_escalation_client": {
        "service": "",
        "service_variant": "",
        "stylist": "",
        "date": "",
        "time": "",
    },
}

_DEFAULT_ADAPTIVE_FLOWS: dict[str, dict[str, Any]] = {
    "booking_complete": {
        "persona_id": "maria_new_client",
        "description": "Complete booking flow from greeting to confirmation",
        "expected_outcome": "appointment_created",
        "completion_condition": "booking_completed",
        "completion_rules": ["booking_completed"],
        "milestones": [
            {
                "name": "greeting_done",
                "intent_classifier": "clarification",
                "expected_keywords": ["hola", "bienvenida"],
                "next_milestone": "service_resolved",
                "fallback_milestone": "greeting_done",
                "description": "Greeting acknowledged",
            },
            {
                "name": "service_resolved",
                "intent_classifier": "clarification",
                "expected_keywords": ["servicio", "dama", "caballero"],
                "next_milestone": "addons_handled",
                "fallback_milestone": "greeting_done",
                "description": "Service resolved",
            },
            {
                "name": "addons_handled",
                "intent_classifier": "clarification",
                "expected_keywords": ["adicional", "tratamiento"],
                "next_milestone": "stylist_resolved",
                "fallback_milestone": "service_resolved",
                "description": "Add-ons handled",
            },
            {
                "name": "stylist_resolved",
                "intent_classifier": "stylist",
                "expected_keywords": ["estilista", "cualquiera"],
                "next_milestone": "slot_resolved",
                "fallback_milestone": "addons_handled",
                "description": "Stylist resolved",
            },
            {
                "name": "slot_resolved",
                "intent_classifier": "slot",
                "expected_keywords": ["horario", "turno", "jueves"],
                "next_milestone": "confirmation_done",
                "fallback_milestone": "stylist_resolved",
                "description": "Slot resolved",
            },
            {
                "name": "confirmation_done",
                "intent_classifier": "confirmation",
                "expected_keywords": ["confirmo", "resumen"],
                "next_milestone": "booking_completed",
                "fallback_milestone": "slot_resolved",
                "description": "Confirmation done",
            },
            {
                "name": "booking_completed",
                "intent_classifier": "completion",
                "expected_keywords": ["agendado", "reservado"],
                "next_milestone": None,
                "fallback_milestone": "confirmation_done",
                "description": "Booking completed",
            },
        ],
    },
    "escalation_flow": {
        "persona_id": "elena_escalation_client",
        "description": "Escalation to human agent",
        "expected_outcome": "escalated_to_human",
        "completion_condition": "escalation_completed",
        "completion_rules": ["escalation_triggered"],
        "milestones": [
            {
                "name": "empathy_shown",
                "intent_classifier": "escalation",
                "expected_keywords": ["entiendo", "disculpa"],
                "next_milestone": "handoff_offered",
                "fallback_milestone": "empathy_shown",
                "description": "Empathy shown",
            },
            {
                "name": "handoff_offered",
                "intent_classifier": "escalation",
                "expected_keywords": ["humano", "equipo"],
                "next_milestone": "escalation_completed",
                "fallback_milestone": "empathy_shown",
                "description": "Human handoff offered",
            },
            {
                "name": "escalation_completed",
                "intent_classifier": "escalation",
                "expected_keywords": ["derivado"],
                "next_milestone": None,
                "fallback_milestone": "handoff_offered",
                "description": "Escalation completed",
            },
        ],
    },
}


class TestingContextManager:
    """Load and expose QA testing context from the repository."""

    CONTEXT_FILE = Path(".atl/qa-testing-context.md")

    def __init__(self, root_path: Path | None = None):
        self.root_path = Path(root_path or Path.cwd())
        self.context_path = self.root_path / self.CONTEXT_FILE
        self._cached_context: QATestingContext | None = None

    def load_context(self, force_reload: bool = False) -> QATestingContext:
        if self._cached_context and not force_reload:
            return self._cached_context

        if not self.context_path.exists():
            raise FileNotFoundError(f"QA testing context file not found: {self.context_path}")

        frontmatter = self._extract_frontmatter(self.context_path.read_text(encoding="utf-8"))
        raw_context = json.loads(frontmatter)

        personas = {
            persona_id: Persona(
                id=persona_id,
                name=data["name"],
                role=data.get("role", "qa persona"),
                description=data["description"],
                behavior=list(data.get("behavior", [])),
                expected_flow=data["expected_flow"],
                typical_phrases=list(data.get("typical_phrases", [])),
            )
            for persona_id, data in (raw_context.get("personas") or {}).items()
        }
        criteria = {
            criteria_id: LevelCriteria(
                id=criteria_id,
                label=data["label"],
                determinism=data["determinism"],
                objective=data["objective"],
                checks=[
                    CheckItem(id=item["id"], description=item["description"])
                    for item in data.get("checks", [])
                ],
            )
            for criteria_id, data in (raw_context.get("criteria") or {}).items()
        }
        flows = {
            flow_id: Flow(
                id=flow_id,
                persona_id=data["persona_id"],
                description=data["description"],
                expected_outcome=data["expected_outcome"],
                steps=[
                    FlowStep(
                        turn=step["turn"],
                        mode=step["mode"],
                        user=step["user"],
                        expect=dict(step.get("expect", {})),
                    )
                    for step in data.get("steps", [])
                ],
            )
            for flow_id, data in (raw_context.get("flows") or {}).items()
        }

        self._cached_context = QATestingContext(
            version=str(raw_context.get("version", "1.0")),
            personas=personas,
            criteria=criteria,
            flows=flows,
        )
        return self._cached_context

    def get_persona(self, persona_id: str) -> Persona:
        context = self.load_context()
        if persona_id not in context.personas:
            available = ", ".join(sorted(context.personas))
            raise ValueError(f"Unknown persona '{persona_id}'. Available personas: {available}")
        return context.personas[persona_id]

    def get_flow(self, flow_id: str) -> Flow:
        context = self.load_context()
        if flow_id not in context.flows:
            available = ", ".join(sorted(context.flows))
            raise ValueError(f"Unknown flow '{flow_id}'. Available flows: {available}")
        return context.flows[flow_id]

    def get_criteria(self) -> dict[str, LevelCriteria]:
        return self.load_context().criteria

    def get_adaptive_persona(self, persona_id: str) -> AdaptivePersona:
        """Load an AdaptivePersona by ID.

        Merges the legacy Persona data from the context file with the
        adaptive preferences from ``_DEFAULT_ADAPTIVE_PERSONAS``.
        Falls back to a synthetic persona when the ID is not in the file
        (e.g. ``elena_escalation_client``).
        """
        prefs_data = _DEFAULT_ADAPTIVE_PERSONAS.get(persona_id, {})
        preferences = AdaptivePreferences(
            service=prefs_data.get("service", ""),
            service_variant=prefs_data.get("service_variant", ""),
            stylist=prefs_data.get("stylist", ""),
            date=prefs_data.get("date", "esta semana"),
            time=prefs_data.get("time", "mañana"),
        )

        # Try to load from file
        try:
            p = self.get_persona(persona_id)
            return AdaptivePersona(
                id=p.id,
                name=p.name,
                role=p.role,
                description=p.description,
                behavior=p.behavior,
                expected_flow=p.expected_flow,
                typical_phrases=p.typical_phrases,
                preferences=preferences,
            )
        except (FileNotFoundError, ValueError):
            # Fallback: synthetic persona
            return AdaptivePersona(
                id=persona_id,
                name=persona_id.replace("_", " ").title(),
                role="qa persona",
                description=f"Synthetic adaptive persona: {persona_id}",
                behavior=[],
                expected_flow="",
                typical_phrases=[],
                preferences=preferences,
            )

    def get_adaptive_flow(self, flow_id: str) -> AdaptiveFlow:
        """Load an AdaptiveFlow by ID from in-memory defaults or file."""
        raw = _DEFAULT_ADAPTIVE_FLOWS.get(flow_id)
        if raw is None:
            # Try legacy flow with a synthetic milestone mapping
            try:
                legacy = self.get_flow(flow_id)
                return AdaptiveFlow(
                    id=legacy.id,
                    persona_id=legacy.persona_id,
                    description=legacy.description,
                    expected_outcome=legacy.expected_outcome,
                    milestones=[],
                    completion_condition=legacy.expected_outcome,
                    completion_rules=[legacy.expected_outcome],
                )
            except (FileNotFoundError, ValueError):
                raise ValueError(
                    f"Unknown adaptive flow '{flow_id}'. "
                    f"Available: {', '.join(sorted(_DEFAULT_ADAPTIVE_FLOWS))}"
                )

        milestones = [
            Milestone(
                name=m["name"],
                intent_classifier=m["intent_classifier"],
                expected_keywords=list(m.get("expected_keywords", [])),
                next_milestone=m.get("next_milestone"),
                fallback_milestone=m.get("fallback_milestone"),
                description=m.get("description", ""),
            )
            for m in raw.get("milestones", [])
        ]

        return AdaptiveFlow(
            id=flow_id,
            persona_id=raw["persona_id"],
            description=raw["description"],
            expected_outcome=raw["expected_outcome"],
            milestones=milestones,
            completion_condition=raw.get("completion_condition", ""),
            completion_rules=list(raw.get("completion_rules", [])),
        )

    def resolve_flow_context(self, flow_id: str, persona_id: str | None = None) -> dict[str, Any]:
        """Resolve flow context for both legacy and adaptive flows.

        Returns a combined dict with:
        - ``flow_id``, ``persona_id`` — from the adaptive flow / persona
        - ``flow`` — the AdaptiveFlow (with ``completion_rules``, ``milestones``)
        - ``milestones`` — list of Milestone objects
        - ``legacy_flow`` — legacy Flow object (or None)
        - ``legacy_steps`` — list of FlowStep (empty list if no legacy steps)
        - ``persona`` — AdaptivePersona
        - ``available_flows`` — sorted list of all available flow IDs
        - ``criteria`` — criteria dict
        """
        adaptive_flow = self.get_adaptive_flow(flow_id)
        resolved_persona_id = persona_id or adaptive_flow.persona_id
        persona = self.get_adaptive_persona(resolved_persona_id)

        # Load legacy flow if it exists
        legacy_flow: Flow | None = None
        legacy_steps: list[FlowStep] = []
        try:
            context = self.load_context()
            legacy_flow = context.flows.get(flow_id)
            if legacy_flow:
                legacy_steps = legacy_flow.steps
        except FileNotFoundError:
            pass

        try:
            context = self.load_context()
            available = sorted(context.flows.keys())
            criteria = context.criteria
        except FileNotFoundError:
            available = sorted(_DEFAULT_ADAPTIVE_FLOWS.keys())
            criteria = {}

        return {
            "flow_id": adaptive_flow.id,
            "persona_id": persona.id,
            "flow": adaptive_flow,
            "milestones": adaptive_flow.milestones,
            "legacy_flow": legacy_flow,
            "legacy_steps": legacy_steps,
            "persona": persona,
            "available_flows": available,
            "criteria": criteria,
        }

    @staticmethod
    def _extract_frontmatter(content: str) -> str:
        if not content.startswith("---\n"):
            raise ValueError("QA testing context must start with YAML frontmatter")

        _, _, remainder = content.partition("---\n")
        frontmatter, separator, _ = remainder.partition("\n---\n")
        if not separator:
            raise ValueError("QA testing context frontmatter is not closed with '---'")
        return frontmatter
