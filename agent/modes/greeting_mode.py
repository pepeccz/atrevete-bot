"""
Greeting Mode — v6.0 Mode-Based Architecture (customer-name-handling refactor).

Handles lightweight first contact for low-intent greetings. This mode NEVER
mentions the customer's name in responses. Customer creation uses
`pending_whatsapp_name` (from Chatwoot sender.name) as the PRIMARY source,
with a regex fallback that extracts the name from message text when WhatsApp
metadata is unavailable.

Flow:
1. If customer already exists (returning): warm name-free greeting → target mode
2. If new customer: create customer silently with sender_name → warm greeting → target mode

Target mode after greeting is determined by `last_intent` in mode_context:
- "book" → BOOKING (user greeted AND wants to book)
- "ask_info" → GENERAL (user greeted AND has a question)
- anything else → GENERAL (default)

NO name in any response.
"""

import logging
import re
import unicodedata

from agent.tools.customer_tools import manage_customer

from agent.modes.base import FIRST_TURN_INTRO, BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# Pre-defined greeting messages (ALL name-free)
# FIX: Removed FIRST_TURN_INTRO from _WELCOME_NEW to avoid duplication.
# FIRST_TURN_INTRO is prepended automatically by BaseModeNode._maybe_prepend_intro() (base.py:257)
_WELCOME_NEW = "¿En qué puedo ayudarte hoy?"
_WELCOME_RETURNING = "¡Hola de nuevo! 😊 ¿En qué puedo ayudarte hoy?"

# ── ADR-4: Audience hint tokens ───────────────────────────────────────────────
# Maps normalized message tokens → audience hint values
_AUDIENCE_HINT_MAP: dict[str, str] = {
    # adult_male
    "caballero": "adult_male",
    "hombre": "adult_male",
    "senor": "adult_male",
    "adulto": "adult_male",
    # adult_female
    "dama": "adult_female",
    "mujer": "adult_female",
    "senora": "adult_female",
    "adulta": "adult_female",
    # child_female
    "nina": "child_female",
    "nena": "child_female",
    "hija": "child_female",
    # child_male
    "nino": "child_male",
    "nene": "child_male",
    "hijo": "child_male",
}

# Tokens that signal booking intent in the greeting message
_BOOKING_CONTENT_TOKENS: frozenset[str] = frozenset({
    "mujer",
    "hombre",
    "nino",
    "nina",
    "dama",
    "caballero",
    "corte",
    "tinte",
    "color",
    "peluqueria",
    "adulta",
    "adulto",
    "turno",
    "reservar",
    "cita",
    "mechas",
    "peinado",
    "quiero",
})


# ── Name extraction fallback (when pending_whatsapp_name is unavailable) ───────
# Patterns match common Spanish self-introduction phrases.
# WhatsApp metadata (pending_whatsapp_name) ALWAYS takes priority over these.
NAME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:me llamo|mi nombre es)\s+"
        r"([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|\.\s+)[Ss]oy\s+"
        r"([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)?)",
    ),
]

_FALSE_POSITIVE_NAMES: frozenset[str] = frozenset({
    "nueva", "nuevo", "cliente", "clienta",
    "de", "la", "el", "un", "una",
})


def _extract_name_from_message(text: str | None) -> str | None:
    """
    Try to extract a customer name from the user's message text.

    Matches patterns like "me llamo María", "soy Juan", "mi nombre es Ana López".
    Returns the name in title case, or None if no valid name is found.

    This is a FALLBACK — only called when pending_whatsapp_name is unavailable.
    """
    if not text:
        return None

    for pattern in NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            # Filter false positives: single-word matches that are common words
            tokens = candidate.lower().split()
            if all(t in _FALSE_POSITIVE_NAMES for t in tokens):
                continue
            return candidate.title()

    return None


def _normalize_text(text: str | None) -> str:
    """Normalize text for comparison: strip, lowercase, remove accents."""
    if not text:
        return ""
    raw = text.strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _has_booking_content(message: str | None) -> bool:
    """
    Return True when the message contains tokens that signal a service request.

    Used to detect when a greeting message also carries booking intent
    (e.g. "Hola, quiero un corte de dama") so the booking context can be
    passed to the next mode even when the router classified it as "greet".

    Args:
        message: Raw user message text (or None).

    Returns:
        True if any booking-intent token is found in the normalized text.
    """
    if not message:
        return False
    normalized = _normalize_text(message)
    return any(token in normalized for token in _BOOKING_CONTENT_TOKENS)


def _build_booking_handoff_context(message: str | None) -> dict:
    """
    Build a booking handoff context dict from a greeting message.

    Extracts:
    - opening_booking_request: the original message text (for intent carry-over)
    - service_audience_hint: audience classification based on keywords

    Args:
        message: Raw user message text (or None).

    Returns:
        Dict with extracted booking context keys, or empty dict if no content.
    """
    if not message:
        return {}
    if not _has_booking_content(message):
        return {}

    ctx: dict = {"opening_booking_request": message}

    normalized = _normalize_text(message)
    for token, hint in _AUDIENCE_HINT_MAP.items():
        if token in normalized:
            ctx["service_audience_hint"] = hint
            break

    return ctx


def _resolve_target_mode(mode_context: dict) -> str:
    """
    Determine which mode to transition to after the greeting.

    ADR-4: Widened gate — also routes to BOOKING when has_booking_content is True
    (not just when last_intent == "book").

    Returns:
        "BOOKING" if last_intent == "book" or "reschedule",
        "GENERAL" otherwise (including greet, ask_info, ambiguous, etc.)
    """
    last_intent = (mode_context or {}).get("last_intent", "greet")
    if last_intent in ("book", "reschedule"):
        return "BOOKING"
    return "GENERAL"


class GreetingMode(BaseModeNode):
    """
    Mode node for first-contact greetings.

    Responsibilities:
    - Send a warm welcome on genuine greeting turns (WITHOUT using customer name)
    - Create customer record silently using sender_name from Chatwoot
    - Transition to the appropriate mode based on detected intent
    """

    @property
    def mode_name(self) -> str:
        return "GREETING"

    @staticmethod
    def _extract_response_text(result: object | None) -> str:
        if result is None:
            return ""
        content = getattr(result, "content", result)
        return str(content).strip()

    async def handle(self, state: ConversationState, intent: object) -> dict:
        """
        Handle the greeting flow.

        Two branches, both name-free:
        1. Returning customer (customer_name exists) → warm greeting → target mode
        2. New customer → create customer silently (soft-fail) → warm greeting → target mode

        ADR-3: Customer creation failure is a soft-fail (continues in GREETING, no escalation).
        ADR-4: Booking content in greeting message is detected and carried over to the
               transition mode_context via _build_booking_handoff_context().

        NEVER mentions the customer's name in any response.

        Args:
            state: Current conversation state
            intent: IntentResult (not used in GREETING — simple sequential flow)

        Returns:
            Partial state update dict
        """
        conversation_id = state.get("conversation_id", "unknown")
        customer_name = state.get("customer_name")
        mode_context = state.get("mode_context") or {}
        is_first = state.get("is_first_interaction", True)

        self.logger.info(
            "GreetingMode.handle | conversation=%s | customer_name=%s | is_first=%s",
            conversation_id,
            customer_name,
            is_first,
        )

        # ADR-4: Extract booking handoff context from the user's greeting message
        # (e.g. "Hola, quiero turno para un caballero" → service_audience_hint = adult_male)
        last_user_message = ""
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user":
                last_user_message = msg.get("content", "")
                break

        booking_handoff = _build_booking_handoff_context(last_user_message)
        has_booking_content = bool(booking_handoff)

        target_mode = _resolve_target_mode(mode_context)

        # ── Branch 1: Returning customer (name already known) ────────────
        if customer_name:
            self.logger.info(
                "GreetingMode: returning customer (name=%s), transitioning to %s",
                customer_name,
                target_mode,
            )
            fallback_response = _WELCOME_RETURNING
            response = await self._render_layered_response(
                state,
                mode_context,
                fallback_response=fallback_response,
                step_name="returning_customer",
                include_history=False,
            )
            final_response, disclosure_sent = self._maybe_prepend_intro(response, state)
            transition_update = transition_mode(state, target_mode)

            # ADR-4: Inject booking handoff context into the new mode_context
            if has_booking_content and booking_handoff:
                new_mode_ctx = {**transition_update.get("mode_context", {}), **booking_handoff}
                transition_update["mode_context"] = new_mode_ctx

            updates = {
                **transition_update,
                **add_message(state, "assistant", final_response),
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Branch 2: New customer ───────────────────────────────────────
        # Create customer silently using pending_whatsapp_name (from Chatwoot sender.name)
        # ADR-3: Soft-fail — customer creation failure does NOT escalate, just continues
        pending_name = state.get("pending_whatsapp_name")

        # ── Fallback: extract name from message text when WhatsApp metadata is absent
        if not pending_name:
            extracted = _extract_name_from_message(last_user_message)
            if extracted:
                self.logger.info(
                    "GreetingMode: extracted name from message text (fallback): %s",
                    extracted,
                )
                pending_name = extracted

        existing_id = state.get("customer_id")

        customer_id: str | None = existing_id or None
        if not customer_id:
            try:
                customer_id = await self._create_customer(state, pending_name)
            except Exception as exc:
                self.logger.warning(
                    "GreetingMode: customer creation failed (soft-fail, continuing): %s | phone=%s",
                    exc,
                    state.get("customer_phone"),
                )
                customer_id = None

        self.logger.info(
            "GreetingMode: new customer | pending_name=%s | customer_id=%s | target_mode=%s",
            pending_name,
            customer_id,
            target_mode,
        )

        # ADR-3: No more escalation on customer creation failure — just continue
        # The user gets a warm greeting, and customer creation will be retried later.

        fallback_response = _WELCOME_NEW
        response = await self._render_layered_response(
            state,
            mode_context,
            fallback_response=fallback_response,
            step_name="welcome",
            include_history=False,
        )
        final_response, disclosure_sent = self._maybe_prepend_intro(response, state)
        transition_update = transition_mode(state, target_mode)

        # ADR-4: Inject booking handoff context into the new mode_context
        if has_booking_content and booking_handoff:
            new_mode_ctx = {**transition_update.get("mode_context", {}), **booking_handoff}
            transition_update["mode_context"] = new_mode_ctx

        updates = {
            **transition_update,
            **add_message(state, "assistant", final_response),
            "user_message": None,
        }
        if customer_id:
            updates["customer_id"] = customer_id
        if pending_name:
            updates["customer_name"] = pending_name
        if disclosure_sent:
            updates["ai_disclosure_sent"] = True
        return updates

    # ── Private helpers ───────────────────────────────────────────────────────

    def _contains_customer_name_token(
        self,
        response_text: str,
        customer_name: str,
    ) -> bool:
        """
        Returns True if any meaningful token from customer_name appears as a
        word-boundary match (case+accent insensitive) in response_text.

        Tokens shorter than 3 chars (prepositions, articles) are skipped
        to avoid false positives on common words.

        Accent normalization: NFD decomposition drops combining marks so
        "María" matches "Maria" and vice-versa.
        """

        def _nfd_lower(text: str) -> str:
            return "".join(
                c for c in unicodedata.normalize("NFD", text.lower())
                if unicodedata.category(c) != "Mn"
            )

        normalized_response = _nfd_lower(response_text)
        tokens = re.split(r"\W+", customer_name)
        for token in tokens:
            if len(token) < 3:
                continue
            normalized_token = _nfd_lower(token)
            pattern = rf"\b{re.escape(normalized_token)}\b"
            if re.search(pattern, normalized_response):
                return True
        return False

    async def _render_layered_response(
        self,
        state: ConversationState,
        mode_context: dict,
        *,
        fallback_response: str,
        step_name: str,
        include_history: bool = False,
    ) -> str:
        """Render a greeting response via layered prompts, falling back to hardcoded."""
        if not self._use_optimized_prompts():
            return fallback_response

        messages = await self._build_layered_messages(
            state,
            mode_context,
            step_name=step_name,
            include_history=include_history,
        )
        response_text = self._extract_response_text(await self._call_llm(messages))

        # Validate: response must NOT contain the customer's name (token-based)
        customer_name = state.get("customer_name") or state.get("pending_whatsapp_name")
        if response_text and customer_name:
            if self._contains_customer_name_token(response_text, customer_name):
                self.logger.warning(
                    "GreetingMode: LLM leaked customer name token in response, using fallback"
                )
                return fallback_response

        if response_text:
            # Also reject responses that ask for name
            lower = response_text.lower()
            if any(token in lower for token in ("nombre", "llamo", "llamas", "llamarte")):
                self.logger.warning(
                    "GreetingMode: LLM asked for name in response, using fallback"
                )
                return fallback_response
            return response_text

        return fallback_response

    async def _create_customer(
        self, state: ConversationState, name: str | None
    ) -> str | None:
        """
        Create a new customer record in the database.

        Uses `name` (from Chatwoot sender.name) as first_name.
        If name is None, creates customer without a name.

        Returns the customer ID string if successful, or None on failure.
        """
        customer_phone = state.get("customer_phone", "")
        if not customer_phone:
            self.logger.warning("GreetingMode: no customer_phone in state — skipping DB creation")
            return None

        try:
            data: dict = {}
            if name:
                data["first_name"] = name

            result = await manage_customer.ainvoke({
                "action": "create",
                "phone": customer_phone,
                "data": data,
            })

            if isinstance(result, dict) and "id" in result and "error" not in result:
                customer_id = str(result["id"])
                self.logger.info(
                    "GreetingMode: customer created | id=%s | name=%s | phone=%s",
                    customer_id,
                    name,
                    customer_phone,
                )
                return customer_id
            else:
                self.logger.warning(
                    "GreetingMode: manage_customer returned unexpected result: %s", result
                )
                return None

        except Exception as exc:
            self.logger.error(
                "GreetingMode: customer creation failed | name=%s | error=%s",
                name,
                exc,
            )
            return None
