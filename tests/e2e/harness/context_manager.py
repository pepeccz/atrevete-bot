"""Context loader for conversational QA scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
                checks=[CheckItem(id=item["id"], description=item["description"]) for item in data.get("checks", [])],
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

    def resolve_flow_context(self, flow_id: str, persona_id: str | None = None) -> dict[str, Any]:
        flow = self.get_flow(flow_id)
        persona = self.get_persona(persona_id or flow.persona_id)
        context = self.load_context()
        return {
            "flow_id": flow.id,
            "persona_id": persona.id,
            "available_flows": sorted(context.flows.keys()),
            "persona": persona,
            "flow": flow,
            "criteria": context.criteria,
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
