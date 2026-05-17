from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.e2e.harness.context_manager import (
    AdaptivePersona,
    Milestone,
)
from tests.e2e.harness.context_manager import (
    TestingContextManager as ContextManager,
)
from tests.e2e.harness.redis_harness import (
    ClassifierOutput,
    MilestoneTracker,
    ReplyGenerator,
    ResponseClassifier,
    RunTerminated,
    extract_options,
)


@pytest.fixture
def testing_manager() -> ContextManager:
    return ContextManager(root_path=Path.cwd())


@pytest.fixture
def adaptive_persona(testing_manager: ContextManager) -> AdaptivePersona:
    return testing_manager.get_adaptive_persona("carlos_returning_client")


@pytest.fixture
def new_client_persona(testing_manager: ContextManager) -> AdaptivePersona:
    return testing_manager.get_adaptive_persona("maria_new_client")


@pytest.fixture
def escalation_persona(testing_manager: ContextManager) -> AdaptivePersona:
    return testing_manager.get_adaptive_persona("elena_escalation_client")


def test_resolve_flow_context_exposes_adaptive_and_legacy_structures(
    testing_manager: ContextManager,
) -> None:
    context = testing_manager.resolve_flow_context("booking_complete")

    assert context["flow_id"] == "booking_complete"
    assert context["persona_id"] == "maria_new_client"
    assert context["flow"].completion_rules == ["booking_completed"]
    assert context["legacy_flow"] is not None
    assert isinstance(context["milestones"], list)
    assert context["milestones"][0].name == "greeting_done"
    assert context["legacy_steps"] == []


def test_adaptive_flow_links_milestones(testing_manager: ContextManager) -> None:
    flow = testing_manager.get_adaptive_flow("booking_complete")

    assert flow.id == "booking_complete"
    assert flow.milestones[0].next_milestone == "service_resolved"
    assert flow.milestones[0].fallback_milestone == "greeting_done"
    assert flow.milestones[-1].name == flow.completion_condition


def test_classifier_with_checkpoint(adaptive_persona) -> None:
    classifier = ResponseClassifier(
        checkpoint_state={"mode_context": {"booking_step": "slot_selection"}}
    )
    milestone = Milestone(
        name="slot_resolved",
        intent_classifier="slot",
        expected_keywords=["horario", "turno"],
        next_milestone="confirmation_done",
        fallback_milestone="stylist_resolved",
        description="Slot selected",
    )

    result = classifier.classify(
        "Te paso horarios disponibles para el jueves.",
        milestone,
        adaptive_persona,
    )

    assert result.intent == "slot"
    assert result.booking_step == "slot_selection"
    assert result.confidence >= 0.74


def test_classifier_fallback_keyword(adaptive_persona) -> None:
    classifier = ResponseClassifier(checkpoint_state=None)
    milestone = Milestone(
        name="stylist_resolved",
        intent_classifier="stylist",
        expected_keywords=["estilista", "cualquiera"],
        next_milestone="slot_resolved",
        fallback_milestone="addons_handled",
        description="Stylist requested",
    )

    result = classifier.classify(
        "Preferis alguna estilista o te va cualquiera?",
        milestone,
        adaptive_persona,
    )

    assert result.intent == "stylist"
    assert result.confidence >= 0.58
    assert "estilista" in result.matched_keywords


def test_classifier_detects_escalation_without_checkpoint(testing_manager: ContextManager) -> None:
    persona = testing_manager.get_adaptive_persona("elena_escalation_client")
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="handoff_offered",
        intent_classifier="escalation",
        expected_keywords=["humano", "equipo"],
        next_milestone="escalation_completed",
        fallback_milestone="empathy_shown",
        description="Human handoff offered",
    )

    result = classifier.classify(
        "Voy a derivarte con una persona del equipo para resolverlo.",
        milestone,
        persona,
    )

    assert result.intent == "escalation"
    assert result.confidence >= 0.6


def test_classifier_greeting_intent(new_client_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="greeting_done",
        intent_classifier="clarification",
        expected_keywords=["hola", "bienvenida"],
        next_milestone="service_resolved",
        fallback_milestone="greeting_done",
        description="Greeting acknowledged",
    )

    result = classifier.classify(
        "Hola, bienvenida a Atrévete. Querés reservar un turno?",
        milestone,
        new_client_persona,
    )

    assert result.intent == "clarification"
    assert result.confidence >= 0.7
    assert "hola" in result.matched_keywords


def test_classifier_service_selection_intent(new_client_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="service_resolved",
        intent_classifier="clarification",
        expected_keywords=["servicio", "dama"],
        next_milestone="addons_handled",
        fallback_milestone="greeting_done",
        description="Service resolved",
    )

    result = classifier.classify(
        "Querés corte para dama o caballero?",
        milestone,
        new_client_persona,
    )

    assert result.intent == "clarification"
    assert result.confidence >= 0.8
    assert "dama" in result.matched_keywords


def test_classifier_stylist_intent(adaptive_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="stylist_resolved",
        intent_classifier="stylist",
        expected_keywords=["luciana", "cualquiera"],
        next_milestone="slot_resolved",
        fallback_milestone="addons_handled",
        description="Stylist resolved",
    )

    result = classifier.classify(
        "Preferís a Luciana o te va cualquiera?",
        milestone,
        adaptive_persona,
    )

    assert result.intent == "stylist"
    assert result.confidence >= 0.68
    assert "Luciana" in result.matched_keywords


def test_classifier_slot_intent(adaptive_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="slot_resolved",
        intent_classifier="slot",
        expected_keywords=["jueves", "horario"],
        next_milestone="confirmation_done",
        fallback_milestone="stylist_resolved",
        description="Slot resolved",
    )

    result = classifier.classify(
        "Tengo horario el jueves a las 10 o a las 11.",
        milestone,
        adaptive_persona,
    )

    assert result.intent == "slot"
    assert result.confidence >= 0.8
    assert "horario" in result.matched_keywords


def test_classifier_confirmation_intent(adaptive_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="confirmation_done",
        intent_classifier="confirmation",
        expected_keywords=["confirmo", "resumen"],
        next_milestone="booking_completed",
        fallback_milestone="slot_resolved",
        description="Confirmation complete",
    )

    result = classifier.classify(
        "Te paso el resumen y si querés confirmo la reserva.",
        milestone,
        adaptive_persona,
    )

    assert result.intent == "confirmation"
    assert result.confidence >= 0.68
    assert "confirmo" in result.matched_keywords


def test_classifier_escalation_intent(escalation_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="handoff_offered",
        intent_classifier="escalation",
        expected_keywords=["humano", "equipo"],
        next_milestone="escalation_completed",
        fallback_milestone="empathy_shown",
        description="Escalation offered",
    )

    result = classifier.classify(
        "Te derivo con una persona del equipo humano para seguir.",
        milestone,
        escalation_persona,
    )

    assert result.intent == "escalation"
    assert result.confidence >= 0.7
    assert "equipo" in result.matched_keywords


def test_classifier_fallback_when_no_keywords_match(adaptive_persona: AdaptivePersona) -> None:
    classifier = ResponseClassifier()
    milestone = Milestone(
        name="notes_pending",
        intent_classifier="notes",
        expected_keywords=["comentario"],
        next_milestone="confirmation_done",
        fallback_milestone="slot_resolved",
        description="Notes requested",
    )

    result = classifier.classify("Entiendo perfectamente.", milestone, adaptive_persona)

    assert result.intent == "notes"
    assert result.confidence == 0.35
    assert result.matched_keywords == ()


def test_reply_generator_deterministic(adaptive_persona) -> None:
    generator = ReplyGenerator()
    classifier_output = ClassifierOutput(intent="stylist", confidence=0.82)
    persona_goals = {
        "name": adaptive_persona.name,
        "stylist": adaptive_persona.preferences.stylist,
        "date": adaptive_persona.preferences.date,
        "time": adaptive_persona.preferences.time,
    }
    history = ["Tenemos a Luciana, Sofi o cualquiera."]

    reply_one = generator.generate_reply(
        persona_goals=persona_goals,
        persona_preferences=adaptive_persona.preferences,
        last_classifier_output=classifier_output,
        conversation_history=history,
    )
    reply_two = generator.generate_reply(
        persona_goals=persona_goals,
        persona_preferences=adaptive_persona.preferences,
        last_classifier_output=classifier_output,
        conversation_history=history,
    )

    assert reply_one == "Luciana"
    assert reply_one == reply_two
    assert len(reply_one) <= 200


def test_reply_generator_handles_confirmation_with_templates(adaptive_persona) -> None:
    generator = ReplyGenerator(
        reply_templates={"confirmation": "Entendido, {name}. Te confirmo {date} {time}."}
    )
    classifier_output = ClassifierOutput(intent="confirmation", confidence=0.91)
    persona_goals = {
        "name": adaptive_persona.name,
        "date": adaptive_persona.preferences.date,
        "time": adaptive_persona.preferences.time,
    }

    reply = generator.generate_reply(
        persona_goals=persona_goals,
        persona_preferences=adaptive_persona.preferences,
        last_classifier_output=classifier_output,
        conversation_history=[],
    )

    assert reply == "Entendido, Carlos. Te confirmo esta semana mañana."
    assert len(reply) <= 200


def test_reply_generator_greeting_for_new_client(new_client_persona: AdaptivePersona) -> None:
    generator = ReplyGenerator()
    classifier_output = ClassifierOutput(intent="clarification", confidence=0.78)
    persona_goals = {
        "name": new_client_persona.name,
        "service": new_client_persona.preferences.service,
        "service_variant": new_client_persona.preferences.service_variant,
    }

    reply = generator.generate_reply(
        persona_goals=persona_goals,
        persona_preferences=new_client_persona.preferences,
        last_classifier_output=classifier_output,
        conversation_history=["Hola, bienvenida. Querés corte para dama o caballero?"],
    )

    assert reply == "dama"


def test_reply_generator_service_reply_matches_persona_preference(
    adaptive_persona: AdaptivePersona,
) -> None:
    generator = ReplyGenerator()
    classifier_output = ClassifierOutput(intent="clarification", confidence=0.82)
    persona_goals = {
        "name": adaptive_persona.name,
        "service": adaptive_persona.preferences.service,
        "service_variant": adaptive_persona.preferences.service_variant,
    }

    reply = generator.generate_reply(
        persona_goals=persona_goals,
        persona_preferences=adaptive_persona.preferences,
        last_classifier_output=classifier_output,
        conversation_history=["Querés corte para dama o caballero?"],
    )

    assert reply == "caballero"


def test_reply_generator_max_200_chars(adaptive_persona: AdaptivePersona) -> None:
    generator = ReplyGenerator(reply_templates={"notes": "{notes_reply}"})
    classifier_output = ClassifierOutput(intent="notes", confidence=0.6)
    persona_goals = {"notes": "x" * 250}

    reply = generator.generate_reply(
        persona_goals=persona_goals,
        persona_preferences=adaptive_persona.preferences,
        last_classifier_output=classifier_output,
        conversation_history=[],
    )

    assert len(reply) == 200
    assert reply.endswith("...")


def test_option_extraction_spanish_numbered() -> None:
    options = extract_options("1. Maria\n2. Pedro\n3. Otro", "stylist")

    assert options == ["Maria", "Pedro", "Otro"]


def test_option_extraction_inline_and_cualquiera() -> None:
    options = extract_options(
        "Tenemos a Maria, Pedro o cualquiera otro estilista.",
        "stylist",
    )

    assert options == ["Maria", "Pedro", "cualquiera"]


def test_extract_inline_options_with_o_separator() -> None:
    options = extract_options("Podés elegir Maria o Pedro o Sofia.", "stylist")

    assert options == ["Maria", "Pedro", "Sofia"]


def test_extract_cualquiera_fallback() -> None:
    options = extract_options("Si querés puede atenderte cualquiera otro estilista.", "stylist")

    assert options == ["cualquiera"]


def test_extract_empty_when_no_options() -> None:
    options = extract_options("Perfecto, ya reviso eso por vos.", "stylist")

    assert options == []


def test_extract_case_insensitive() -> None:
    options = extract_options("TENEMOS a lUcIaNa o CUALQUIERA.", "stylist")

    assert options == ["LUcIaNa", "cualquiera"]


def test_milestone_tracker_completion() -> None:
    tracker = MilestoneTracker(
        current_milestone=Milestone(
            name="completed",
            intent_classifier="completion",
            expected_keywords=["agendado"],
            next_milestone=None,
            fallback_milestone="confirmation_done",
            description="Run completed",
        )
    )

    with pytest.raises(RunTerminated, match="completed after 1 turns") as exc_info:
        tracker.record_turn(
            classifier_output=ClassifierOutput(intent="completion", confidence=0.95),
            booking_row_exists=True,
        )

    assert exc_info.value.outcome == "completed"
    assert tracker.outcome_reason == "completed after 1 turns"


def test_milestone_tracker_escalation() -> None:
    tracker = MilestoneTracker(
        current_milestone=Milestone(
            name="handoff_offered",
            intent_classifier="escalation",
            expected_keywords=["equipo"],
            next_milestone="escalation_completed",
            fallback_milestone="empathy_shown",
            description="Handoff offered",
        )
    )

    with pytest.raises(RunTerminated, match="escalation triggered") as exc_info:
        tracker.record_turn(
            classifier_output=ClassifierOutput(intent="escalation", confidence=0.8)
        )

    assert exc_info.value.outcome == "escalation"


def test_milestone_tracker_timeout() -> None:
    tracker = MilestoneTracker(
        current_milestone=Milestone(
            name="slot_resolved",
            intent_classifier="slot",
            expected_keywords=["horario"],
            next_milestone="confirmation_done",
            fallback_milestone="stylist_resolved",
            description="Slot selection",
        ),
        max_turns=1,
    )

    tracker.record_turn(classifier_output=ClassifierOutput(intent="slot", confidence=0.8))
    with pytest.raises(RunTerminated, match="timeout after 2 turns") as exc_info:
        tracker.record_turn(classifier_output=ClassifierOutput(intent="slot", confidence=0.8))

    assert exc_info.value.outcome == "timeout"


def test_milestone_tracker_dead_loop() -> None:
    tracker = MilestoneTracker(
        current_milestone=Milestone(
            name="stylist_resolved",
            intent_classifier="stylist",
            expected_keywords=["estilista"],
            next_milestone=None,
            fallback_milestone="addons_handled",
            description="Stylist selection",
        ),
        started_at=datetime.now(UTC) - timedelta(seconds=10),
    )

    tracker.record_turn(classifier_output=ClassifierOutput(intent="clarification", confidence=0.4))
    tracker.record_turn(classifier_output=ClassifierOutput(intent="clarification", confidence=0.4))
    with pytest.raises(RunTerminated, match="dead loop detected") as exc_info:
        tracker.record_turn(classifier_output=ClassifierOutput(intent="clarification", confidence=0.4))

    assert exc_info.value.outcome == "dead_loop"


def test_tracker_stops_on_max_turns() -> None:
    slot_milestone = Milestone(
        name="slot_resolved",
        intent_classifier="slot",
        expected_keywords=["horario"],
        next_milestone="confirmation_done",
        fallback_milestone="stylist_resolved",
        description="Slot selection",
    )
    confirmation_milestone = Milestone(
        name="confirmation_done",
        intent_classifier="confirmation",
        expected_keywords=["confirmo"],
        next_milestone="slot_resolved",
        fallback_milestone="stylist_resolved",
        description="Confirmation pending",
    )
    tracker = MilestoneTracker(
        current_milestone=slot_milestone,
        max_turns=15,
    )

    for turn_index in range(15):
        tracker.record_turn(
            classifier_output=ClassifierOutput(intent="clarification", confidence=0.4),
            next_milestone=confirmation_milestone if turn_index % 2 == 0 else slot_milestone,
        )

    with pytest.raises(RunTerminated, match="timeout after 16 turns") as exc_info:
        tracker.record_turn(classifier_output=ClassifierOutput(intent="clarification", confidence=0.4))

    assert exc_info.value.outcome == "timeout"


def test_tracker_does_not_false_positive_on_clarification() -> None:
    tracker = MilestoneTracker(
        current_milestone=Milestone(
            name="greeting_done",
            intent_classifier="clarification",
            expected_keywords=["hola"],
            next_milestone="service_resolved",
            fallback_milestone="greeting_done",
            description="Greeting complete",
        )
    )

    tracker.record_turn(
        classifier_output=ClassifierOutput(intent="clarification", confidence=0.4),
        next_milestone=Milestone(
            name="service_resolved",
            intent_classifier="clarification",
            expected_keywords=["servicio"],
            next_milestone="stylist_resolved",
            fallback_milestone="greeting_done",
            description="Service resolved",
        ),
    )
    tracker.record_turn(
        classifier_output=ClassifierOutput(intent="clarification", confidence=0.4),
        next_milestone=Milestone(
            name="stylist_resolved",
            intent_classifier="stylist",
            expected_keywords=["estilista"],
            next_milestone="slot_resolved",
            fallback_milestone="service_resolved",
            description="Stylist resolved",
        ),
    )

    assert tracker.turn_count == 2
    assert tracker.current_milestone.name == "stylist_resolved"
    assert tracker.outcomes_seen == set()
