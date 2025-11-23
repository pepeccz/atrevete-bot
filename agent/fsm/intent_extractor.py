"""
Intent Extractor - LLM-based intent extraction for FSM hybrid architecture.

This module implements state-aware intent extraction using GPT-4.1-mini via OpenRouter.
The LLM focuses on NLU (Natural Language Understanding) while the FSM controls flow.

Key responsibilities:
- Extract user intent from natural language messages
- Provide state-aware disambiguation (e.g., "1" means different things in different states)
- Extract relevant entities (service names, numbers, customer data)
- Return structured Intent objects for FSM validation

Architecture (ADR-006):
    LLM (NLU)      → Interpreta INTENCIÓN + Genera LENGUAJE
    FSM Control    → Controla FLUJO + Valida PROGRESO + Decide TOOLS
    Tool Calls     → Ejecuta ACCIONES validadas
"""

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.fsm.models import BookingState, Intent, IntentType
from shared.config import get_settings

logger = logging.getLogger(__name__)

# Confidence threshold below which we return UNKNOWN
MIN_CONFIDENCE_THRESHOLD = 0.7

# ============================================================================
# INTENT SYNONYMS (Bug #1 fix)
# ============================================================================
# Maps common Spanish variations to canonical IntentType values.
# This normalizer runs AFTER LLM extraction but BEFORE Intent creation,
# catching cases where the LLM outputs valid Spanish but unmapped intent names.
#
# Context-aware: Some words map differently based on FSM state (handled in extraction prompt)
# This dict handles the most common fallback mappings.

INTENT_SYNONYMS: dict[str, str] = {
    # confirm_services variations (SERVICE_SELECTION state)
    "continua": "confirm_services",
    "continúa": "confirm_services",
    "continue": "confirm_services",
    "seguir": "confirm_services",
    "sigamos": "confirm_services",
    "ya está": "confirm_services",
    "ya esta": "confirm_services",
    "solo eso": "confirm_services",
    "nada más": "confirm_services",
    "nada mas": "confirm_services",
    "eso es todo": "confirm_services",
    "listo": "confirm_services",
    # confirm_booking variations (CONFIRMATION state)
    "confirmo": "confirm_booking",
    "confirmar": "confirm_booking",
    "perfecto": "confirm_booking",
    "adelante": "confirm_booking",  # Context: in CONFIRMATION state
    "procede": "confirm_booking",
    "proceder": "confirm_booking",
    "vale": "confirm_booking",
    "ok": "confirm_booking",
    "dale": "confirm_booking",
    # start_booking variations
    "reservar": "start_booking",
    "agendar": "start_booking",
    "cita": "start_booking",
    "quiero una cita": "start_booking",
    # cancel_booking variations
    "cancelar": "cancel_booking",
    "no quiero": "cancel_booking",
    "dejarlo": "cancel_booking",
}


def _get_llm_client() -> ChatOpenAI:
    """
    Get LLM client for intent extraction.

    Uses same OpenRouter configuration as conversational_agent but with lower temperature
    for more deterministic intent classification.
    """
    settings = get_settings()

    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.1,  # Low temperature for deterministic classification
        default_headers={
            "HTTP-Referer": settings.SITE_URL,
            "X-Title": settings.SITE_NAME,
        },
    )


def _build_state_context(
    current_state: BookingState, collected_data: dict[str, Any]
) -> str:
    """
    Build state-specific context for the intent extraction prompt.

    This enables STATE-AWARE disambiguation - the same message ("1") can mean
    different things depending on the current FSM state.

    Args:
        current_state: Current FSM state
        collected_data: Data accumulated so far in the booking flow

    Returns:
        Context string describing current state and valid intents
    """
    # Define valid intents per state
    state_intents: dict[BookingState, list[tuple[str, str]]] = {
        BookingState.IDLE: [
            ("start_booking", "Usuario quiere hacer una reserva/cita"),
            ("greeting", "Saludo sin intención de reserva"),
            ("faq", "Pregunta sobre horarios, servicios, precios, ubicación"),
            ("escalate", "Quiere hablar con una persona o está frustrado"),
        ],
        BookingState.SERVICE_SELECTION: [
            ("select_service", "Usuario selecciona un servicio (nombre o número)"),
            ("confirm_services", "Usuario confirma que no quiere más servicios"),
            # Allow select_stylist from SERVICE_SELECTION when LLM shows stylists without
            # explicit confirmation (user has at least 1 service selected)
            ("select_stylist", "Usuario selecciona un estilista (si ya tiene servicios)"),
            ("cancel_booking", "Usuario quiere cancelar la reserva"),
            ("faq", "Pregunta sobre horarios, servicios, precios"),
            ("escalate", "Quiere hablar con una persona"),
        ],
        BookingState.STYLIST_SELECTION: [
            ("select_stylist", "Usuario selecciona un estilista (nombre o número)"),
            ("cancel_booking", "Usuario quiere cancelar la reserva"),
            ("faq", "Pregunta sobre estilistas, horarios"),
            ("escalate", "Quiere hablar con una persona"),
        ],
        BookingState.SLOT_SELECTION: [
            ("select_slot", "Usuario selecciona una hora/fecha (número o texto)"),
            ("check_availability", "Quiere ver más opciones de horarios"),
            ("cancel_booking", "Usuario quiere cancelar la reserva"),
            ("faq", "Pregunta sobre horarios"),
            ("escalate", "Quiere hablar con una persona"),
        ],
        BookingState.CUSTOMER_DATA: [
            ("provide_customer_data", "Usuario da su nombre y/o datos"),
            ("cancel_booking", "Usuario quiere cancelar la reserva"),
            ("escalate", "Quiere hablar con una persona"),
        ],
        BookingState.CONFIRMATION: [
            ("confirm_booking", "Usuario confirma la reserva (sí, adelante, confirmo)"),
            ("cancel_booking", "Usuario quiere cancelar (no, cancelar)"),
            ("escalate", "Quiere hablar con una persona"),
        ],
        BookingState.BOOKED: [
            ("greeting", "Saludo o despedida"),
            ("faq", "Pregunta sobre la cita confirmada"),
            ("escalate", "Quiere hablar con una persona"),
        ],
    }

    # Get valid intents for current state
    valid_intents = state_intents.get(current_state, [])
    intents_text = "\n".join([f"- {name}: {desc}" for name, desc in valid_intents])

    # Build collected data summary
    data_summary_parts = []
    if collected_data.get("services"):
        services = collected_data["services"]
        data_summary_parts.append(f"Servicios seleccionados: {', '.join(services)}")
    if collected_data.get("stylist_id"):
        data_summary_parts.append(f"Estilista ID: {collected_data['stylist_id']}")
    if collected_data.get("slot"):
        slot = collected_data["slot"]
        data_summary_parts.append(f"Horario: {slot.get('start_time', 'pendiente')}")
    if collected_data.get("first_name"):
        data_summary_parts.append(f"Nombre: {collected_data['first_name']}")

    data_summary = (
        "\n".join(data_summary_parts) if data_summary_parts else "Ninguno aún"
    )

    # State-specific disambiguation hints (Bug #1 fix: expanded variations)
    disambiguation_hints: dict[BookingState, str] = {
        BookingState.SERVICE_SELECTION: (
            "IMPORTANTE: Un número (1, 2, 3...) puede ser:\n"
            "- Selección de SERVICIO si la lista mostrada es de servicios\n"
            "- Selección de ESTILISTA si la lista mostrada es de estilistas\n"
            "Analiza el CONTEXTO RECIENTE para determinar qué tipo de lista se mostró.\n"
            "Si el asistente mostró 'Ana', 'María', 'Carlos' = usuario selecciona estilista.\n\n"
            "CONFIRMACIÓN DE SERVICIOS (intent: confirm_services):\n"
            "'Sí', 'eso es todo', 'nada más', 'continua', 'continúa', 'adelante', "
            "'sigamos', 'ya está', 'solo eso', 'listo', 'seguir' = confirm_services"
        ),
        BookingState.STYLIST_SELECTION: (
            "IMPORTANTE: Un número (1, 2, 3...) significa selección de estilista de la lista.\n"
            "Un nombre como 'Maria' o 'con quien sea' = select_stylist"
        ),
        BookingState.SLOT_SELECTION: (
            "IMPORTANTE: Un número (1, 2, 3...) significa selección de horario de la lista.\n"
            "Una fecha/hora como 'mañana a las 10' = select_slot"
        ),
        BookingState.CUSTOMER_DATA: (
            "IMPORTANTE: Cualquier nombre proporcionado = provide_customer_data.\n"
            "Extraer first_name (obligatorio) y last_name (opcional)"
        ),
        BookingState.CONFIRMATION: (
            "CONFIRMACIÓN DE RESERVA (intent: confirm_booking):\n"
            "'Sí', 'si', 'confirmo', 'adelante', 'perfecto', 'ok', 'vale', 'dale', "
            "'correcto', 'procede', 'listo' = confirm_booking\n\n"
            "CANCELACIÓN (intent: cancel_booking):\n"
            "'No', 'cancelar', 'espera', 'no quiero', 'dejarlo' = cancel_booking"
        ),
    }

    hint = disambiguation_hints.get(current_state, "")

    return f"""ESTADO ACTUAL: {current_state.value}
DATOS RECOPILADOS:
{data_summary}

INTENCIONES VÁLIDAS PARA ESTE ESTADO:
{intents_text}

{hint}"""


def _build_extraction_prompt(
    message: str,
    current_state: BookingState,
    collected_data: dict[str, Any],
    conversation_history: list[dict[str, Any]],
) -> str:
    """
    Build the complete prompt for intent extraction.

    The prompt is designed to:
    1. Be state-aware for disambiguation
    2. Include recent conversation context
    3. Output structured JSON for reliable parsing
    """
    state_context = _build_state_context(current_state, collected_data)

    # Include last 3 messages for context (if available)
    recent_context = ""
    if conversation_history:
        recent_messages = conversation_history[-3:]
        recent_parts = []
        for msg in recent_messages:
            role = "Usuario" if msg.get("role") == "user" else "Asistente"
            content = msg.get("content", "")[:100]  # Truncate for prompt size
            recent_parts.append(f"{role}: {content}")
        recent_context = "\n".join(recent_parts)

    return f"""Eres un analizador de intenciones para un bot de reservas de peluquería.
Tu ÚNICA tarea es identificar la intención del usuario y extraer entidades relevantes.

{state_context}

CONTEXTO RECIENTE DE LA CONVERSACIÓN:
{recent_context if recent_context else "Primera interacción"}

MENSAJE DEL USUARIO: "{message}"

INSTRUCCIONES:
1. Analiza el mensaje considerando el ESTADO ACTUAL
2. Identifica la intención más probable de la lista de INTENCIONES VÁLIDAS
3. Extrae entidades relevantes según el tipo de intención
4. Asigna un nivel de confianza (0.0 a 1.0)

FORMATO DE RESPUESTA (JSON estricto):
{{
    "intent_type": "nombre_de_intencion",
    "entities": {{
        "service_name": "nombre si aplica",
        "selection_number": numero si aplica,
        "stylist_id": "id si aplica",
        "first_name": "nombre si aplica",
        "last_name": "apellido si aplica",
        "slot_time": "hora si aplica",
        "notes": "notas si aplica"
    }},
    "confidence": 0.95
}}

REGLAS DE EXTRACCIÓN DE ENTIDADES:
- select_service: Extraer service_name (texto) o selection_number (número de lista)
- select_stylist: Extraer stylist_id o selection_number
- select_slot: Extraer slot_time o selection_number
- provide_customer_data: Extraer first_name (requerido), last_name (opcional), notes (opcional)
- Para otros intents: entities puede estar vacío {{}}

Responde SOLO con el JSON, sin explicaciones adicionales."""


def _parse_llm_response(response_text: str, raw_message: str) -> Intent:
    """
    Parse LLM response into Intent object.

    Handles parsing errors gracefully by returning UNKNOWN intent.
    """
    try:
        # Try to extract JSON from response
        # Sometimes LLM adds markdown code blocks
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)

        # Parse intent type with synonym normalization (Bug #1 fix)
        intent_type_str = data.get("intent_type", "unknown")

        # Normalize using INTENT_SYNONYMS before trying to parse as IntentType
        normalized_intent = INTENT_SYNONYMS.get(intent_type_str.lower(), intent_type_str)
        if normalized_intent != intent_type_str:
            logger.info(
                f"Intent normalized: '{intent_type_str}' -> '{normalized_intent}'"
            )
            intent_type_str = normalized_intent

        try:
            intent_type = IntentType(intent_type_str)
        except ValueError:
            logger.warning(
                f"Unknown intent type from LLM: {intent_type_str}, defaulting to UNKNOWN"
            )
            intent_type = IntentType.UNKNOWN

        # Parse entities
        entities = data.get("entities", {})
        # Clean up None values
        entities = {k: v for k, v in entities.items() if v is not None}

        # Parse confidence
        confidence = float(data.get("confidence", 0.0))

        # If confidence below threshold, return UNKNOWN
        if confidence < MIN_CONFIDENCE_THRESHOLD:
            logger.info(
                f"Intent confidence {confidence:.2f} below threshold "
                f"{MIN_CONFIDENCE_THRESHOLD}, returning UNKNOWN"
            )
            return Intent(
                type=IntentType.UNKNOWN,
                entities={},
                confidence=confidence,
                raw_message=raw_message,
            )

        return Intent(
            type=intent_type,
            entities=entities,
            confidence=confidence,
            raw_message=raw_message,
        )

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse LLM response: {e}, response: {response_text[:200]}")
        return Intent(
            type=IntentType.UNKNOWN,
            entities={},
            confidence=0.0,
            raw_message=raw_message,
        )


async def extract_intent(
    message: str,
    current_state: BookingState,
    collected_data: dict[str, Any],
    conversation_history: list[dict[str, Any]],
) -> Intent:
    """
    Extract user intent from message using LLM with state-aware disambiguation.

    The LLM receives context about the current FSM state to correctly interpret
    ambiguous messages (e.g., "1" in SERVICE_SELECTION vs "1" in SLOT_SELECTION).

    Args:
        message: User's raw message text
        current_state: Current FSM state for disambiguation
        collected_data: Data accumulated so far in the booking flow
        conversation_history: Recent conversation messages for context

    Returns:
        Intent object with type, entities, confidence, and raw_message.
        Returns IntentType.UNKNOWN with confidence=0.0 on any error.

    Example:
        >>> intent = await extract_intent(
        ...     "Quiero una cita",
        ...     BookingState.IDLE,
        ...     {},
        ...     []
        ... )
        >>> intent.type
        IntentType.START_BOOKING
        >>> intent.confidence >= 0.8
        True
    """
    start_time = time.time()

    logger.info(
        f"Extracting intent | state={current_state.value} | message={message[:50]}..."
    )

    try:
        # Build prompt
        prompt = _build_extraction_prompt(
            message, current_state, collected_data, conversation_history
        )

        # Get LLM client
        llm = _get_llm_client()

        # Invoke LLM
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content="Eres un analizador de intenciones. Responde SOLO en JSON."
                ),
                HumanMessage(content=prompt),
            ]
        )

        # Parse response
        intent = _parse_llm_response(response.content, message)

        # Log latency and result
        latency_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Intent extracted | type={intent.type.value} | confidence={intent.confidence:.2f} "
            f"| latency={latency_ms:.0f}ms | entities={list(intent.entities.keys())}"
        )

        return intent

    except Exception as e:
        # Fallback to UNKNOWN on any error - never raise exceptions
        latency_ms = (time.time() - start_time) * 1000

        logger.error(
            f"Intent extraction failed | error={str(e)} | latency={latency_ms:.0f}ms",
            exc_info=True,
        )

        return Intent(
            type=IntentType.UNKNOWN,
            entities={},
            confidence=0.0,
            raw_message=message,
        )
