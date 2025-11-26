"""
Response Validator - Post-validation of LLM responses for FSM coherence (Story 5-7a).

This module implements the Response Coherence Layer (Phase 1) that validates
LLM responses against the current FSM state before sending to users.

Architecture:
    LLM generates response
         ↓
    ResponseValidator.validate()  ← THIS MODULE
         ↓
    ✅ Coherent → Send to user
    ❌ Incoherent → Regenerate with correction_hint → Send to user

Key Concepts:
- Validates LLM responses don't mention information from future FSM states
- Uses precompiled regex patterns for <100ms validation (no network I/O)
- Provides correction hints to guide LLM regeneration
- Maximum 1 regeneration attempt to avoid infinite loops
"""

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.fsm.models import BookingState, CoherenceResult
from shared.config import get_settings

if TYPE_CHECKING:
    from agent.fsm.booking_fsm import BookingFSM

logger = logging.getLogger(__name__)


# ============================================================================
# FORBIDDEN PATTERNS BY STATE
# ============================================================================
# Maps FSM states to regex patterns that indicate incoherent responses.
# Patterns are stored as raw strings and compiled once at module load.

_FORBIDDEN_PATTERNS_RAW: dict[BookingState, list[tuple[str, str]]] = {
    # SERVICE_SELECTION: User is selecting services, shouldn't see stylists or time slots
    BookingState.SERVICE_SELECTION: [
        # Stylist names - the specific stylists at Atrévete salon
        (r"\b(Ana|María|Carlos|Pilar|Laura)\b", "Menciona nombres de estilistas"),
        # Availability/time patterns indicating slot information
        (r"disponible[s]?\s+(a las|el|mañana|lunes|martes|miércoles|jueves|viernes|sábado)",
         "Menciona disponibilidad de horarios"),
        # Time slot presentation
        (r"\d{1,2}:\d{2}\s*(h|horas)?", "Muestra horarios específicos (HH:MM)"),
        # Stylist selection prompt
        (r"(qué|cual|con qué)\s+estilista", "Pregunta por estilista antes de confirmar servicios"),
    ],

    # STYLIST_SELECTION: User is selecting stylist, shouldn't see specific time slots
    BookingState.STYLIST_SELECTION: [
        # Specific time slots (HH:MM format)
        (r"\b\d{1,2}:\d{2}\b", "Muestra horarios específicos antes de seleccionar estilista"),
        # Day of week in availability context
        (r"(lunes|martes|miércoles|jueves|viernes|sábado)\s+\d{1,2}",
         "Muestra días con disponibilidad antes de seleccionar estilista"),
        # Slot confirmation
        (r"(reservar|agendar)\s+(para|a las)\s+\d", "Intenta reservar slot sin estilista seleccionado"),
        # Service selection language (concatenated response from old message)
        (r"(qué tipo de corte|quieres cortarte|cortarte el pelo|muestre las opciones)",
         "Pregunta sobre servicios cuando ya está seleccionando estilista"),
        # Greeting after booking started (indicates concatenated response)
        (r"¡?Hola[,!]?\s+(veo que|me llamo|soy|encantad|buen)",
         "Saludo de inicio cuando ya está en flujo de reserva"),
    ],

    # SLOT_SELECTION: User is selecting time slot, shouldn't confirm or ask for customer data
    BookingState.SLOT_SELECTION: [
        # Premature confirmation - various patterns
        (r"(cita|reserva)\s+(ha sido\s+)?(confirmada|reservada|agendada)", "Confirma cita antes de seleccionar slot"),
        (r"(ha sido|está)\s+(confirmada|reservada|agendada)", "Indica confirmación prematura de cita"),
        (r"reserva\s+está\s+completa", "Indica reserva completa prematuramente"),
        # Customer data requests (should happen after slot selection)
        (r"(tu nombre|tus datos|cómo te llamas)", "Solicita datos del cliente antes de seleccionar slot"),
        # Booking summary (premature)
        (r"resumen de (tu|la) (cita|reserva)", "Muestra resumen antes de completar slot"),
        # Service selection language (concatenated response from old message)
        (r"(qué tipo de corte|quieres cortarte|cortarte el pelo|muestre las opciones)",
         "Pregunta sobre servicios cuando ya está seleccionando horario"),
        (r"servicios de corte disponibles", "Lista servicios cuando ya está seleccionando horario"),
        # Greeting after booking started (indicates concatenated response)
        (r"¡?Hola[,!]?\s+(veo que|me llamo|soy|encantad|buen)",
         "Saludo de inicio cuando ya está en flujo de reserva"),
        # Stylist selection language (going backwards)
        (r"(qué|cuál|con qué)\s+estilista", "Pregunta por estilista cuando ya está seleccionando horario"),
    ],

    # CUSTOMER_DATA: Collecting customer info, shouldn't confirm without name
    BookingState.CUSTOMER_DATA: [
        # Confirmation without required data - various patterns
        (r"(cita|reserva)\s+(ha sido\s+)?(confirmada|reservada|agendada)", "Confirma cita sin datos del cliente"),
        (r"(ha sido|está)\s+(confirmada|reservada|agendada)", "Indica confirmación prematura de cita"),
        # Booking complete message
        (r"(hemos|he)\s+(reservado|agendado|confirmado)", "Indica reserva completa sin datos"),
        # Service selection language (concatenated response from old message)
        (r"(qué tipo de corte|quieres cortarte|cortarte el pelo|muestre las opciones)",
         "Pregunta sobre servicios cuando ya está recopilando datos"),
        # Greeting after booking started (indicates concatenated response)
        (r"¡?Hola[,!]?\s+(veo que|me llamo|soy|encantad|buen)",
         "Saludo de inicio cuando ya está en flujo de reserva"),
    ],

    # CONFIRMATION: Waiting for user confirmation - most responses are valid
    BookingState.CONFIRMATION: [
        # No forbidden patterns - user is confirming the booking
    ],

    # IDLE/BOOKED: General states with no specific restrictions
    BookingState.IDLE: [],
    BookingState.BOOKED: [],
}


# ============================================================================
# COMPILED PATTERNS (Performance optimization - compile once at import)
# ============================================================================

FORBIDDEN_PATTERNS: dict[BookingState, list[tuple[re.Pattern[str], str]]] = {
    state: [(re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in patterns]
    for state, patterns in _FORBIDDEN_PATTERNS_RAW.items()
}


# ============================================================================
# CORRECTION HINTS BY STATE
# ============================================================================
# Templates for correction hints when violations are detected

CORRECTION_HINTS: dict[BookingState, str] = {
    BookingState.SERVICE_SELECTION: (
        "CORRECCIÓN: El usuario está seleccionando SERVICIOS. "
        "NO menciones estilistas ni horarios específicos. "
        "Pregunta qué servicios desea o confirma los servicios seleccionados."
    ),
    BookingState.STYLIST_SELECTION: (
        "CORRECCIÓN: El usuario está seleccionando ESTILISTA. "
        "NO menciones horarios específicos (HH:MM). "
        "Presenta las estilistas disponibles y pregunta cuál prefiere."
    ),
    BookingState.SLOT_SELECTION: (
        "CORRECCIÓN: El usuario está seleccionando HORARIO. "
        "NO confirmes la cita ni pidas datos del cliente todavía. "
        "Muestra los horarios disponibles y pregunta cuál prefiere."
    ),
    BookingState.CUSTOMER_DATA: (
        "CORRECCIÓN: Estás recopilando DATOS DEL CLIENTE. "
        "NO confirmes la cita como completada. "
        "Pide el nombre del cliente para continuar con la reserva."
    ),
    BookingState.CONFIRMATION: (
        "El usuario debe confirmar la cita. "
        "Muestra el resumen y pregunta si desea confirmar."
    ),
    BookingState.IDLE: "",
    BookingState.BOOKED: "",
}


# ============================================================================
# GENERIC FALLBACK RESPONSE
# ============================================================================

GENERIC_FALLBACK_RESPONSE = (
    "¡Hola! 🌸 Soy el asistente de Atrévete Peluquería. "
    "¿En qué puedo ayudarte hoy? ¿Te gustaría agendar una cita?"
)


# ============================================================================
# RESPONSE VALIDATOR CLASS
# ============================================================================


class ResponseValidator:
    """
    Validates LLM responses for coherence with FSM state.

    Implements Phase 1 of the Response Coherence Layer (Story 5-7a).
    Uses precompiled regex patterns for fast validation (<100ms).

    Example:
        >>> validator = ResponseValidator()
        >>> fsm = BookingFSM("conv-123")
        >>> fsm._state = BookingState.SERVICE_SELECTION
        >>> response = "Las estilistas disponibles son: 1. Ana, 2. María"
        >>> result = validator.validate(response, fsm)
        >>> result.is_coherent
        False
        >>> result.violations
        ['Menciona nombres de estilistas']
    """

    def __init__(self) -> None:
        """Initialize ResponseValidator with precompiled patterns."""
        self._patterns = FORBIDDEN_PATTERNS
        self._correction_hints = CORRECTION_HINTS

    def validate(
        self,
        response: str,
        fsm: "BookingFSM",
    ) -> CoherenceResult:
        """
        Validate if an LLM response is coherent with the current FSM state.

        Args:
            response: The LLM-generated response text
            fsm: BookingFSM instance with current state

        Returns:
            CoherenceResult indicating coherence status, violations, and correction hint
        """
        start_time = time.perf_counter()

        # Get patterns for current FSM state
        patterns = self._patterns.get(fsm.state, [])

        # Check patterns and collect violations
        violations = self._check_patterns(response, patterns)

        # Generate result
        is_coherent = len(violations) == 0
        correction_hint = None
        confidence = 1.0

        if not is_coherent:
            correction_hint = self._generate_correction_hint(violations, fsm.state)
            # Confidence based on number of violations (more violations = more confident it's wrong)
            confidence = min(0.99, 0.7 + (len(violations) * 0.1))

        validation_time_ms = (time.perf_counter() - start_time) * 1000

        # Log validation result (AC #7)
        self._log_validation(
            response=response,
            fsm=fsm,
            is_coherent=is_coherent,
            violations=violations,
            validation_time_ms=validation_time_ms,
        )

        return CoherenceResult(
            is_coherent=is_coherent,
            violations=violations,
            correction_hint=correction_hint,
            confidence=confidence,
        )

    def _check_patterns(
        self,
        response: str,
        patterns: list[tuple[re.Pattern[str], str]],
    ) -> list[str]:
        """
        Check response against forbidden patterns.

        Args:
            response: The response text to check
            patterns: List of (compiled_pattern, description) tuples

        Returns:
            List of violation descriptions
        """
        violations = []

        for pattern, description in patterns:
            if pattern.search(response):
                violations.append(description)

        return violations

    def _generate_correction_hint(
        self,
        violations: list[str],
        fsm_state: BookingState,
    ) -> str:
        """
        Generate a correction hint for the LLM based on violations.

        Args:
            violations: List of detected violations
            fsm_state: Current FSM state

        Returns:
            Correction hint string for LLM
        """
        base_hint = self._correction_hints.get(fsm_state, "")

        if not base_hint:
            # Fallback for states without specific hints
            violations_str = ", ".join(violations)
            return f"CORRECCIÓN: Evita lo siguiente: {violations_str}"

        return base_hint

    def _log_validation(
        self,
        response: str,
        fsm: "BookingFSM",
        is_coherent: bool,
        violations: list[str],
        validation_time_ms: float,
    ) -> None:
        """
        Log validation result with FSM context (AC #7).

        Args:
            response: Original response (will be truncated in log)
            fsm: BookingFSM instance
            is_coherent: Validation result
            violations: List of violations if any
            validation_time_ms: Time taken for validation
        """
        # Truncate response for logging (max 200 chars)
        response_preview = response[:200] + "..." if len(response) > 200 else response

        extra = {
            "fsm_state": fsm.state.value,
            "conversation_id": fsm.conversation_id,
            "is_coherent": is_coherent,
            "violations_count": len(violations),
            "validation_time_ms": round(validation_time_ms, 2),
            "collected_data_keys": list(fsm.collected_data.keys()),
        }

        if is_coherent:
            logger.info(
                "Response coherence validated | state=%s | coherent=True | time=%.2fms",
                fsm.state.value,
                validation_time_ms,
                extra=extra,
            )
        else:
            extra["violations"] = violations
            logger.warning(
                "Response coherence FAILED | state=%s | violations=%s | response_preview='%s' | time=%.2fms",
                fsm.state.value,
                violations,
                response_preview,
                validation_time_ms,
                extra=extra,
            )


# ============================================================================
# REGENERATION FUNCTION
# ============================================================================


async def regenerate_with_correction(
    messages: list[Any],
    correction_hint: str,
    fsm: "BookingFSM",
) -> str:
    """
    Regenerate an LLM response with correction hint after coherence validation failure.

    This function is called when ResponseValidator detects an incoherent response.
    It adds a correction hint as a SystemMessage and requests a new response.

    Args:
        messages: Original LangChain message list
        correction_hint: Hint from ResponseValidator for correcting the response
        fsm: BookingFSM instance for context

    Returns:
        Regenerated response string

    Note:
        - Maximum 1 regeneration attempt (enforced by caller)
        - Uses same LLM configuration as main conversational agent
    """
    settings = get_settings()

    # Create LLM instance (same config as conversational_agent)
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.3,
        default_headers={
            "HTTP-Referer": settings.SITE_URL,
            "X-Title": settings.SITE_NAME,
        }
    )

    # Build correction message
    correction_message = SystemMessage(content=f"""
{correction_hint}

Estado FSM actual: {fsm.state.value}
Datos recopilados: {fsm.collected_data}

IMPORTANTE: Genera una respuesta que sea coherente con el estado actual.
NO violes las restricciones del estado {fsm.state.value}.
""")

    # Add correction message to the conversation
    # Insert after the last SystemMessage or at the beginning
    messages_with_correction = list(messages)  # Copy to avoid mutation

    # Find insertion point (after system messages)
    insert_idx = 0
    for i, msg in enumerate(messages_with_correction):
        if isinstance(msg, SystemMessage):
            insert_idx = i + 1
        else:
            break

    messages_with_correction.insert(insert_idx, correction_message)

    # Log regeneration attempt
    logger.info(
        "Regenerating response with correction | state=%s | hint_preview='%s'",
        fsm.state.value,
        correction_hint[:100],
        extra={
            "fsm_state": fsm.state.value,
            "conversation_id": fsm.conversation_id,
            "correction_hint_length": len(correction_hint),
        }
    )

    try:
        response = await llm.ainvoke(messages_with_correction)
        regenerated_content = response.content

        logger.info(
            "Response regenerated successfully | state=%s | response_preview='%s'",
            fsm.state.value,
            regenerated_content[:100] if regenerated_content else "empty",
            extra={
                "fsm_state": fsm.state.value,
                "conversation_id": fsm.conversation_id,
                "response_length": len(regenerated_content) if regenerated_content else 0,
            }
        )

        return regenerated_content or GENERIC_FALLBACK_RESPONSE

    except Exception as e:
        logger.error(
            "Failed to regenerate response | state=%s | error=%s",
            fsm.state.value,
            str(e),
            extra={
                "fsm_state": fsm.state.value,
                "conversation_id": fsm.conversation_id,
                "error": str(e),
            },
            exc_info=True,
        )

        # Return generic fallback on error
        return GENERIC_FALLBACK_RESPONSE


# ============================================================================
# LOGGING HELPER
# ============================================================================


def log_coherence_metrics(
    fsm: "BookingFSM",
    original_coherent: bool,
    regenerated: bool,
    regeneration_coherent: bool | None,
    total_time_ms: float,
) -> None:
    """
    Log coherence validation metrics for monitoring.

    Args:
        fsm: BookingFSM instance
        original_coherent: Whether original response was coherent
        regenerated: Whether regeneration was attempted
        regeneration_coherent: Whether regenerated response was coherent (None if not regenerated)
        total_time_ms: Total time including regeneration if applicable
    """
    extra = {
        "fsm_state": fsm.state.value,
        "conversation_id": fsm.conversation_id,
        "original_coherent": original_coherent,
        "regenerated": regenerated,
        "regeneration_coherent": regeneration_coherent,
        "total_time_ms": round(total_time_ms, 2),
    }

    if original_coherent:
        logger.info(
            "Coherence metrics | state=%s | original_coherent=True | time=%.2fms",
            fsm.state.value,
            total_time_ms,
            extra=extra,
        )
    elif regenerated and regeneration_coherent:
        logger.info(
            "Coherence metrics | state=%s | regenerated=True | regen_coherent=True | time=%.2fms",
            fsm.state.value,
            total_time_ms,
            extra=extra,
        )
    elif regenerated and not regeneration_coherent:
        logger.warning(
            "Coherence metrics | state=%s | regenerated=True | regen_coherent=False | using_fallback | time=%.2fms",
            fsm.state.value,
            total_time_ms,
            extra=extra,
        )
    else:
        logger.warning(
            "Coherence metrics | state=%s | original_coherent=False | no_regeneration | time=%.2fms",
            fsm.state.value,
            total_time_ms,
            extra=extra,
        )
