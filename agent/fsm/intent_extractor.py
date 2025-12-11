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

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.sql import func

from agent.fsm.models import BookingState, Intent, IntentType
from database.connection import get_async_session
from database.models import Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

# ============================================================================
# DYNAMIC STYLIST CACHE (replaces hardcoded STYLIST_NAME_TO_ID)
# ============================================================================
# In-memory cache for stylist name -> ID mapping
# Loaded from database on first use, cached for 10 minutes
# This prevents UUID mismatch bugs when database is re-seeded
_stylist_cache: dict[str, str] = {}
_stylist_cache_lock = asyncio.Lock()
_stylist_cache_timestamp: float = 0.0
STYLIST_CACHE_TTL_SECONDS: int = 600  # 10 minutes

# Madrid timezone for datetime normalization
MADRID_TZ = ZoneInfo("Europe/Madrid")

# Confidence threshold below which we return UNKNOWN
MIN_CONFIDENCE_THRESHOLD = 0.7


def _normalize_start_time_timezone(start_time: str) -> str:
    """
    Normalize start_time to ensure it has Europe/Madrid timezone.

    Root cause fix for book() failures: LLM sometimes extracts start_time without timezone
    (e.g., "2025-11-27T10:30:00") but book() expects ISO 8601 with timezone
    (e.g., "2025-11-27T10:30:00+01:00").

    Args:
        start_time: ISO 8601 datetime string, possibly without timezone

    Returns:
        ISO 8601 datetime string WITH timezone (+01:00 or +02:00 depending on DST)

    Examples:
        >>> _normalize_start_time_timezone("2025-11-27T10:30:00")
        "2025-11-27T10:30:00+01:00"

        >>> _normalize_start_time_timezone("2025-11-27T10:30:00+01:00")
        "2025-11-27T10:30:00+01:00"  # Already has timezone, preserved
    """
    try:
        # Check if timezone info already present (ends with +XX:XX, -XX:XX, or Z)
        if re.search(r'[+-]\d{2}:\d{2}$', start_time) or start_time.endswith('Z'):
            logger.debug(f"start_time '{start_time}' already has timezone, preserving")
            return start_time

        # Parse as naive datetime and add Madrid timezone
        naive_dt = datetime.fromisoformat(start_time)
        aware_dt = naive_dt.replace(tzinfo=MADRID_TZ)
        normalized = aware_dt.isoformat()

        logger.info(
            f"Normalized start_time timezone: '{start_time}' → '{normalized}'"
        )
        return normalized

    except ValueError as e:
        logger.warning(
            f"Could not parse start_time '{start_time}' for timezone normalization: {e}. "
            f"Returning original value."
        )
        return start_time

# ============================================================================
# INTENT SYNONYMS (Bug #1 fix)
# ============================================================================
# Maps common Spanish variations to canonical IntentType values.
# This normalizer runs AFTER LLM extraction but BEFORE Intent creation,
# catching cases where the LLM outputs valid Spanish but unmapped intent names.
#
# Context-aware: Some words map differently based on FSM state (handled in extraction prompt)
# This dict handles the most common fallback mappings.

# ============================================================================
# GENERIC SERVICE TERMS (Bug #1 fix - post-extraction validation)
# ============================================================================
# These are generic terms that indicate the user is DESCRIBING what they want,
# NOT selecting a specific service from a list.
# If LLM extracts select_service with ONLY a generic term (no selection_number),
# we convert to FAQ intent to show the service list.
#
# Example: "Quiero cortarme el pelo" → LLM might extract {service_name: "corte"}
# This should be FAQ (to show haircut options), NOT select_service.

# Note: This list should NOT include valid service name substrings like "corte", "tinte", etc.
# because "Corte de Caballero" might be abbreviated as "Corte" by the user.
# Instead, focus on VERB FORMS and BODY PARTS that indicate descriptions, not selections.
GENERIC_SERVICE_TERMS: set[str] = {
    # Verb forms that indicate desire/description, NOT selection
    "cortarme", "cortarse", "cortarme el pelo", "cortarme pelo", "cortarmelo",
    "teñir", "teñirme", "teñirmelo",
    "peinar", "peinarme",
    "tratar", "tratarme",
    # Body parts that indicate description
    "pelo", "cabello", "pelo largo", "pelo corto", "el pelo",
    "uñas", "las uñas",
    # Generic descriptors (too vague to be service selections)
    "algo", "cita", "servicio", "servicios",
}

# Patterns in the raw message that indicate the user is DESCRIBING what they want,
# not SELECTING a specific service. Used for Bug #1 post-extraction validation.
DESCRIPTION_PATTERNS: list[str] = [
    "quiero cortarme",
    "quiero teñirme",
    "quiero peinarme",
    "quiero tratarme",
    "me gustaría",
    "me gustaria",
    "necesito un",
    "necesito una",
    "busco un",
    "busco una",
    "quiero un corte",
    "quiero una cita",
    "quiero hacerme",
]


async def _load_stylist_cache() -> dict[str, str]:
    """
    Load stylist name -> ID mapping from database.

    Uses in-memory cache with 10-minute TTL to avoid repeated DB queries.
    Returns dict mapping lowercase names to UUIDs.

    This replaces the hardcoded STYLIST_NAME_TO_ID dict to prevent
    UUID mismatch bugs when the database is re-seeded.
    """
    global _stylist_cache, _stylist_cache_timestamp

    async with _stylist_cache_lock:
        current_time = time.time()

        # Return cached data if still valid
        if _stylist_cache and (current_time - _stylist_cache_timestamp) < STYLIST_CACHE_TTL_SECONDS:
            return _stylist_cache

        logger.info("Loading stylist cache from database")

        try:
            async with get_async_session() as session:
                stmt = select(Stylist).where(Stylist.is_active == True)
                result = await session.execute(stmt)
                stylists = result.scalars().all()

                new_cache: dict[str, str] = {}
                for stylist in stylists:
                    name_lower = stylist.name.lower().strip()
                    stylist_id = str(stylist.id)
                    new_cache[name_lower] = stylist_id

                    # Also add without accents for common variations
                    name_no_accents = (
                        name_lower
                        .replace("á", "a")
                        .replace("é", "e")
                        .replace("í", "i")
                        .replace("ó", "o")
                        .replace("ú", "u")
                    )
                    if name_no_accents != name_lower:
                        new_cache[name_no_accents] = stylist_id

                _stylist_cache = new_cache
                _stylist_cache_timestamp = current_time

                logger.info(f"Stylist cache loaded: {len(_stylist_cache)} entries")

            return _stylist_cache

        except Exception as e:
            logger.error(f"Error loading stylist cache: {e}", exc_info=True)
            return _stylist_cache  # Return stale cache on error


async def get_stylist_id_by_name(name: str) -> Optional[str]:
    """
    Get stylist UUID by name using dynamic database lookup.

    Args:
        name: Stylist name (case-insensitive)

    Returns:
        Stylist UUID if found, None otherwise
    """
    cache = await _load_stylist_cache()
    name_lower = name.lower().strip()

    # Direct lookup
    if name_lower in cache:
        return cache[name_lower]

    # Try without accents
    name_no_accents = (
        name_lower
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    if name_no_accents in cache:
        return cache[name_no_accents]

    # Partial match (e.g., "Ana" matches "Ana Maria")
    for cached_name, stylist_id in cache.items():
        if cached_name.startswith(name_lower) or name_lower in cached_name:
            logger.info(f"Partial stylist match: '{name}' -> '{cached_name}'")
            return stylist_id

    return None

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
        request_timeout=15.0,  # 15s timeout for intent extraction (simple task)
        max_retries=2,  # Retry 2x on transient failures
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
            ("update_name", "Usuario corrige o proporciona su nombre (ej: 'Llamame X', 'Mi nombre es Y', 'Soy Z')"),
            ("escalate", "Quiere hablar con una persona o está frustrado"),
        ],
        BookingState.SERVICE_SELECTION: [
            ("select_service", "Usuario SELECCIONA un servicio por número o nombre EXACTO de la lista"),
            ("confirm_services", "Usuario confirma que no quiere más servicios"),
            # Allow select_stylist from SERVICE_SELECTION when LLM shows stylists without
            # explicit confirmation (user has at least 1 service selected)
            ("select_stylist", "Usuario selecciona un estilista (si ya tiene servicios)"),
            ("cancel_booking", "Usuario quiere cancelar la reserva"),
            ("faq", "Pregunta o DESCRIBE lo que quiere (ej: 'quiero cortarme', 'me gustaría un tinte')"),
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
            ("confirm_stylist_change", "Usuario confirma cambio de estilista: 'sí', 'vale', 'de acuerdo'"),  # v4.2
            ("check_availability", "Quiere ver más opciones de horarios"),
            ("cancel_booking", "Usuario quiere cancelar la reserva"),
            ("faq", "Pregunta sobre horarios"),
            ("escalate", "Quiere hablar con una persona"),
        ],
        BookingState.CUSTOMER_DATA: [
            ("provide_customer_data", "Usuario da nombre directamente y/o datos"),
            ("use_customer_name", "Usuario dice 'sí', 'para mí', 'mi nombre'"),  # v6.0
            ("provide_third_party_booking", "Usuario dice 'para otra persona' sin dar nombre"),  # v6.0
            ("confirm_name", "Usuario confirma nombre mostrado: 'sí', 'correcto'"),  # v6.0
            ("correct_name", "Usuario corrige su nombre: 'no, mi nombre es X'"),  # v6.0
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
            ("start_booking", "Quiere hacer una NUEVA reserva (además de la existente)"),
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
    if collected_data.get("notes"):
        data_summary_parts.append(f"Notas: {collected_data['notes']}")

    data_summary = (
        "\n".join(data_summary_parts) if data_summary_parts else "Ninguno aún"
    )

    # State-specific disambiguation hints (Bug #1 fix: expanded variations)
    disambiguation_hints: dict[BookingState, str] = {
        BookingState.IDLE: (
            "DISTINGUIR entre:\n"
            "1. ACTUALIZACIÓN DE NOMBRE: 'Llamame X', 'Mi nombre es Y', 'Soy Z', 'No, me llamo W'\n"
            "   → intent: update_name, entities: {first_name: X/Y/Z/W}\n"
            "2. RESERVA: 'Quiero una cita', 'Reservar corte', 'Agendar peinado'\n"
            "   → intent: start_booking\n"
            "3. SALUDO SIMPLE: 'Hola', 'Buenos días' (sin mención de nombre ni servicio)\n"
            "   → intent: greeting\n"
        ),
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
            "IMPORTANTE: Distinguir entre CHECK_AVAILABILITY, SELECT_SLOT y CONFIRM_STYLIST_CHANGE:\n\n"
            "✅ SELECT_SLOT requiere selección CONCRETA de la lista mostrada:\n"
            "- Un NÚMERO de slot (ej: '3', 'el segundo', 'opción 2')\n"
            "- Una HORA ESPECÍFICA que aparezca en la lista (ej: '10:00', '14:30')\n"
            "- Confirmación de slot mostrado ('sí', 'ese', 'perfecto') cuando hay slots listados\n\n"
            "✅ CONFIRM_STYLIST_CHANGE (v4.2) cuando el bot pregunta si acepta otro estilista:\n"
            "- 'sí', 'vale', 'de acuerdo', 'me parece bien', 'ok' → CONFIRM_STYLIST_CHANGE\n"
            "- Solo aplica cuando el contexto muestra pregunta sobre cambio de estilista\n\n"
            "❌ CHECK_AVAILABILITY cuando usuario menciona:\n"
            "- UNA FECHA SIN HORA (ej: 'diciembre 7', 'el viernes', 'mañana')\n"
            "  → Usuario quiere VER slots disponibles, NO seleccionar\n"
            "- Rangos temporales vagos (ej: 'por la tarde', 'por la mañana')\n"
            "- Solicitudes de más opciones (ej: 'otro día', 'más horarios', 'otro')\n\n"
            "⚠️ REGLA CLAVE: Si el usuario menciona una fecha/día SIN especificar "
            "una hora de la lista mostrada, es CHECK_AVAILABILITY, NO SELECT_SLOT."
        ),
        BookingState.CUSTOMER_DATA: (
            "IMPORTANTE: Distinguir entre 3 sub-fases según contexto del mensaje anterior del bot:\n\n"

            "SUB-FASE 1a (pregunta inicial '¿Para quién es la cita? ¿Uso tu nombre?'):\n"
            "- Usuario dice 'sí', 'para mí', 'mi nombre' → USE_CUSTOMER_NAME\n"
            "- Usuario dice 'para otra persona' SIN dar nombre → PROVIDE_THIRD_PARTY_BOOKING\n"
            "- Usuario dice 'para María López' (nombre directo) → PROVIDE_CUSTOMER_DATA con first_name/last_name\n\n"

            "SUB-FASE 1b (bot mostró nombre y pregunta '¿Es correcto?'):\n"
            "- Usuario confirma: 'sí', 'correcto', 'está bien' → CONFIRM_NAME\n"
            "- Usuario corrige: 'no, mi nombre es José García' → CORRECT_NAME con first_name/last_name\n\n"

            "SUB-FASE 1c (bot pregunta '¿Cuál es el nombre?'):\n"
            "- Usuario da nombre → PROVIDE_CUSTOMER_DATA con first_name/last_name\n\n"

            "SUB-FASE 2 (bot pregunta por notas/preferencias):\n"
            "- Usuario responde → PROVIDE_CUSTOMER_DATA con notes (o sin entities si dice 'no')\n"
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

    # Include last 4 messages for context (if available)
    # Assistant messages get more chars to preserve numbered lists for resolution
    recent_context = ""
    if conversation_history:
        recent_messages = conversation_history[-4:]
        recent_parts = []
        for msg in recent_messages:
            role = "Usuario" if msg.get("role") == "user" else "Asistente"
            content = msg.get("content", "")
            # Assistant messages may contain numbered lists - keep more context
            if msg.get("role") == "assistant":
                content = content[:600]  # Enough to capture numbered lists
            else:
                content = content[:150]  # User messages are typically shorter
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
        "stylist_name": "nombre del estilista si aplica (NO incluir UUID)",
        "start_time": "datetime ISO si aplica (ej: 2025-11-25T10:00:00+01:00)",
        "slot_time": "hora simple si aplica (ej: 10:00)",
        "first_name": "nombre si aplica",
        "last_name": "apellido si aplica",
        "notes": "notas/preferencias si aplica"
    }},
    "confidence": 0.95,
    "service_query": "palabras clave del servicio (ver reglas abajo)"
}}

REGLAS DE EXTRACCIÓN DE ENTIDADES:
- select_service:
  * SOLO usar cuando el usuario hace una SELECCIÓN EXPLÍCITA de un servicio mostrado
  * Si el usuario dice un NÚMERO (ej: "5", "el tercero"), DEBES buscar en el CONTEXTO RECIENTE
    la lista numerada mostrada por el Asistente y extraer AMBOS campos:
    - selection_number: el número seleccionado
    - service_name: el nombre EXACTO del servicio de la lista (sin la duración)
    Ejemplo: Si el contexto tiene "5. Corte de Caballero (40 min)" y usuario dice "5"
    → entities: {{"selection_number": 5, "service_name": "Corte de Caballero"}}
  * Si el usuario dice el NOMBRE EXACTO de un servicio del catálogo → solo service_name
    Ejemplo: "Corte de Caballero", "Tinte de Raíces" → select_service
  * ⚠️ NO extraer service_name de DESCRIPCIONES o DESEOS del usuario:
    - "quiero cortarme el pelo" → NO es select_service, es FAQ o búsqueda
    - "me gustaría un tinte" → NO es select_service
    - Solo selecciones EXPLÍCITAS de la lista o nombres EXACTOS del catálogo
- select_stylist:
  * Si el usuario dice un NOMBRE (ej: "Pilar", "Ana"), extrae el nombre del estilista
    Ejemplo: Usuario dice "Pilar" → entities: {{"stylist_name": "Pilar"}}
  * Si dice un NÚMERO, buscar en el CONTEXTO RECIENTE la lista de estilistas mostrada
    y extraer el nombre correspondiente
    Ejemplo: Contexto tiene "4. Pilar", usuario dice "4"
    → entities: {{"selection_number": 4, "stylist_name": "Pilar"}}
  * IMPORTANTE: NO intentes adivinar stylist_id (UUID), solo extrae el nombre.
    El sistema resolverá el UUID automáticamente desde la base de datos.
- select_slot:
  * Si el usuario dice un NÚMERO (ej: "2", "el primero"), buscar en el CONTEXTO RECIENTE
    la lista de horarios mostrada por el Asistente y extraer:
    - selection_number: el número seleccionado
    - start_time: el datetime ISO completo CON TIMEZONE (ej: "2025-11-25T10:00:00+01:00")
    Ejemplo: Si el contexto tiene "2. 10:00 - 11:30 (Pilar)" y usuario dice "2"
    → entities: {{"selection_number": 2, "start_time": "2025-11-25T10:00:00+01:00"}}
  * Si el usuario dice una HORA (ej: "a las 10", "10:00"), buscar en el CONTEXTO RECIENTE
    la fecha de los slots mostrados y extraer:
    - slot_time: "10:00"
    - start_time: datetime completo si está disponible en contexto
  * IMPORTANTE: El contexto de slots tiene "full_datetime" - usar ese valor para start_time
- check_availability (estado SLOT_SELECTION):
  * Cuando el usuario quiere ver MAS OPCIONES de horarios sin seleccionar uno específico
  * Si dice 'tarde', 'por la tarde' → entities: {{"time_range": "afternoon"}}
  * Si dice 'mañana', 'por la mañana' → entities: {{"time_range": "morning"}}
  * Si especifica una fecha como '1 de diciembre' → entities: {{"date": "1 diciembre"}}
  * Si dice 'otro día', 'más opciones' → entities vacío {{}} (sin time_range ni date)
  * IMPORTANTE: "Por la tarde" ≠ "15:00" - el primero es un RANGO, el segundo es ESPECÍFICO
- provide_customer_data (estado CUSTOMER_DATA):
  * Si el usuario da un NOMBRE → extraer first_name (y last_name si aplica)
  * Si el usuario da PREFERENCIAS/NOTAS → extraer notes="contenido de las preferencias"
  * Si el usuario dice "no", "ninguna", "no tengo" cuando se le piden notas → entities vacío {{}}
  * NOTA: El FSM maneja internamente el tracking de fases, solo extrae los datos
- Para otros intents: entities puede estar vacío {{}}

EXTRACCIÓN DE service_query (SIEMPRE rellenar cuando intent=start_booking o intent=faq sobre servicios):
- Extrae SOLO las palabras clave del servicio que el usuario quiere
- ELIMINA saludos (hola, holaaa, buenos días), frases de cortesía, y verbos auxiliares
- NORMALIZA verbos a sustantivos de servicios (IMPORTANTE para búsqueda):
  * teñir/teñirme/teñido/pintarme → "tinte" o "color"
  * cortar/cortarme/cortármelo → "corte"
  * peinar/peinarme → "peinado"
  * depilar/depilarme → "depilación"
  * maquillar/maquillarme → "maquillaje"
  * alisar/alisarme → "alisado"
  * rizar/rizarme → "permanente"
- MANTÉN descriptores útiles junto al sustantivo normalizado:
  * "teñirme el pelo rubio" → service_query: "tinte rubio" o "color rubio"
  * "cortarme el pelo corto" → service_query: "corte corto"
  * "quiero hacerme las mechas" → service_query: "mechas"
- Ejemplos completos:
  * "Holaaa quiero hacerme las mechas" → service_query: "mechas"
  * "Buenos días, quisiera cortarme el pelo" → service_query: "corte"
  * "Hola! Quiero teñirme el pelo" → service_query: "tinte" o "color"
  * "Me gustaría tratamiento keratina" → service_query: "tratamiento keratina"
  * "Quiero hacerme las uñas" → service_query: "uñas manicura"
  * "Quiero depilarme las cejas" → service_query: "depilación cejas"
- Si no hay servicio específico mencionado, dejar vacío: service_query: ""

Responde SOLO con el JSON, sin explicaciones adicionales."""


async def _parse_llm_response(response_text: str, raw_message: str) -> Intent:
    """
    Parse LLM response into Intent object.

    Handles parsing errors gracefully by returning UNKNOWN intent.
    Now async to support dynamic stylist ID lookup from database.
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
        # Ensure entities is a dict (LLM sometimes returns list for multiple selections)
        if not isinstance(entities, dict):
            logger.warning(f"Entities is not a dict: {type(entities)} - converting to empty dict")
            entities = {}
        # Clean up None values and empty strings
        entities = {k: v for k, v in entities.items() if v is not None and v != ""}

        # ============================================================
        # INTENT-AWARE ENTITY FILTERING (Root cause fix for ghost services)
        # ============================================================
        # Each intent type has a whitelist of allowed entities.
        # This prevents START_BOOKING from carrying invalid service entities
        # that the LLM incorrectly extracted from natural language descriptions.
        #
        # Example bug prevented:
        #   User: "quiero cortarme el pelo" → LLM extracts service_name="Corte de Pelo"
        #   Without filtering: FSM stores "Corte de Pelo" as valid service (WRONG)
        #   With filtering: services entity is discarded for START_BOOKING intent
        INTENT_ALLOWED_ENTITIES: dict[IntentType, set[str]] = {
            IntentType.START_BOOKING: set(),  # No entities - just signals intent to book
            IntentType.GREETING: set(),  # No entities needed
            IntentType.FAQ: {"query"},  # Optional search query
            IntentType.ESCALATE: {"reason"},  # Optional reason
            IntentType.SELECT_SERVICE: {"services", "service_name", "selection_number"},
            IntentType.CONFIRM_SERVICES: set(),  # No entities - just confirmation
            IntentType.SELECT_STYLIST: {"stylist_id", "stylist_name", "selection_number"},
            IntentType.CHECK_AVAILABILITY: {"date", "date_range", "time_range"},  # Optional date/time hints
            IntentType.SELECT_SLOT: {"slot", "start_time", "slot_time", "selection_number"},
            IntentType.PROVIDE_CUSTOMER_DATA: {"first_name", "last_name", "notes"},
            IntentType.CONFIRM_BOOKING: set(),  # No entities - just confirmation
            IntentType.CANCEL_BOOKING: {"reason"},  # Optional reason
            IntentType.UNKNOWN: set(),  # No entities for unknown
            IntentType.UPDATE_NAME: {"first_name", "last_name"},  # Name update in IDLE state
        }

        allowed_entities = INTENT_ALLOWED_ENTITIES.get(intent_type, set())
        filtered_entities = {k: v for k, v in entities.items() if k in allowed_entities}

        if entities != filtered_entities:
            discarded = set(entities.keys()) - set(filtered_entities.keys())
            logger.info(
                f"Intent-aware filtering: discarded entities {discarded} for {intent_type.value} "
                f"(allowed: {allowed_entities})"
            )
        entities = filtered_entities

        # Convert service_name to services list (FSM expects "services" not "service_name")
        if "service_name" in entities and "services" not in entities:
            service_name = entities.pop("service_name")
            # Only add non-empty service names
            if service_name and service_name.strip():
                entities["services"] = [service_name.strip()]
                logger.info(f"Converted service_name '{service_name}' to services list")
            else:
                logger.warning("Skipping empty service_name in entity conversion")

        # ============================================================
        # BUG #1 FIX: Post-extraction validation for select_service
        # ============================================================
        # Detect if LLM incorrectly classified a DESCRIPTION as select_service
        # This happens when user says "quiero cortarme el pelo" and LLM extracts
        # select_service with service_name="corte" (generic term).
        #
        # Rule: select_service MUST have either:
        #   1. A selection_number (user selected from numbered list)
        #   2. An EXACT service name (not a generic term) AND the raw message
        #      doesn't contain description patterns like "quiero cortarme"
        # Otherwise, convert to FAQ so LLM shows service options.
        if intent_type == IntentType.SELECT_SERVICE:
            has_selection_number = "selection_number" in entities
            services_list = entities.get("services", [])
            raw_lower = raw_message.lower().strip()

            # Check if all services are generic terms
            all_generic = all(
                service.lower().strip() in GENERIC_SERVICE_TERMS
                for service in services_list
            ) if services_list else False

            # Check if raw message contains description patterns
            has_description_pattern = any(
                pattern in raw_lower for pattern in DESCRIPTION_PATTERNS
            )

            # If no number AND (generic terms OR description pattern) → convert to FAQ
            if not has_selection_number and (all_generic or has_description_pattern):
                logger.warning(
                    f"Bug #1 fix: Converting select_service to faq | "
                    f"services={services_list}, all_generic={all_generic}, "
                    f"has_description_pattern={has_description_pattern}"
                )
                intent_type = IntentType.FAQ
                # Keep the entities - the FAQ handler can use them for search
                # but remove "services" since it's invalid for FAQ
                entities.pop("services", None)

        # Convert stylist_name to stylist_id (FSM expects "stylist_id" UUID)
        # Uses dynamic database lookup instead of hardcoded mapping
        if "stylist_name" in entities and "stylist_id" not in entities:
            stylist_name = entities.get("stylist_name", "")
            stylist_id = await get_stylist_id_by_name(stylist_name)
            if stylist_id:
                entities["stylist_id"] = stylist_id
                logger.info(
                    f"Resolved stylist_name '{stylist_name}' to stylist_id '{stylist_id}' (from DB)"
                )
            else:
                logger.warning(
                    f"Could not resolve stylist_name '{stylist_name}' to stylist_id (not found in DB)"
                )

        # Convert start_time to slot dict (FSM expects "slot" with start_time and duration_minutes)
        # Duration is set to 0 here - will be synchronized by FSM.calculate_service_durations()
        # which is triggered when entering CUSTOMER_DATA state (after slot selection)
        if "start_time" in entities and "slot" not in entities:
            raw_start_time = entities.pop("start_time")
            # CRITICAL: Normalize timezone to prevent book() failures
            # LLM sometimes extracts without timezone (e.g., "2025-11-27T10:30:00")
            # but book() expects ISO 8601 with timezone (e.g., "2025-11-27T10:30:00+01:00")
            normalized_start_time = _normalize_start_time_timezone(raw_start_time)
            entities["slot"] = {
                "start_time": normalized_start_time,
                "duration_minutes": 0,  # Will be synchronized by FSM when entering CUSTOMER_DATA
            }
            logger.info(
                f"Converted start_time to slot dict: raw='{raw_start_time}', "
                f"normalized='{normalized_start_time}' (duration=0, will be synced by FSM)"
            )

        # Convert slot_time to slot dict (when user says "a las 10:30" without full datetime)
        # The FSM will resolve this against the slots_shown list to get the full datetime
        if "slot_time" in entities and "slot" not in entities:
            slot_time = entities.pop("slot_time")
            entities["slot"] = {
                "slot_time": slot_time,  # Will be resolved by FSM using slots_shown context
                "duration_minutes": 0,
            }
            logger.info(
                f"Converted slot_time '{slot_time}' to slot dict (needs FSM resolution against slots_shown)"
            )

        # Parse confidence
        confidence = float(data.get("confidence", 0.0))

        # Parse service_query (cleaned keywords for search_services)
        service_query = data.get("service_query", "")
        if service_query:
            service_query = service_query.strip()
            logger.info(f"Extracted service_query: '{service_query}'")

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
                service_query=service_query or None,
            )

        return Intent(
            type=intent_type,
            entities=entities,
            confidence=confidence,
            raw_message=raw_message,
            service_query=service_query or None,
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

        # Parse response (async to support dynamic stylist lookup)
        intent = await _parse_llm_response(response.content, message)

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
