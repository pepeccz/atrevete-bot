"""
Greeting Mode — v6.0 Mode-Based Architecture (customer-name-handling refactor).

Handles lightweight first contact for low-intent greetings. This mode NEVER
extracts or mentions the customer's name. Customer creation uses
`pending_whatsapp_name` (from Chatwoot sender.name) silently.

Flow:
1. If customer already exists (returning): warm name-free greeting → target mode
2. If new customer: create customer silently with sender_name → warm greeting → target mode

Target mode after greeting is determined by `last_intent` in mode_context:
- "book" → BOOKING (user greeted AND wants to book)
- "ask_info" → GENERAL (user greeted AND has a question)
- anything else → GENERAL (default)

NO name extraction from message text. NO name in any response.
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
_WELCOME_NEW = f"{FIRST_TURN_INTRO} ¿En qué puedo ayudarte hoy?"
_WELCOME_RETURNING = "¡Hola de nuevo! 😊 ¿En qué puedo ayudarte hoy?"


def _resolve_target_mode(mode_context: dict) -> str:
    """
    Determine which mode to transition to after the greeting.

    When the user's message contained a greeting AND an actionable intent
    (e.g. "Hola, quiero cortarme el pelo"), the router stores the classified
    intent in mode_context["last_intent"].  We use it to send the user to the
    right mode instead of always defaulting to GENERAL.

    Returns:
        "BOOKING" if last_intent == "book",
        "GENERAL" otherwise (including greet, ask_info, ambiguous, etc.)
    """
    last_intent = (mode_context or {}).get("last_intent", "greet")
    if last_intent == "book":
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
        1. Returning customer (customer_name exists) → warm greeting → GENERAL
        2. New customer → create customer silently → warm greeting → GENERAL

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

        # ── Branch 1: Returning customer (name already known) ────────────
        target_mode = _resolve_target_mode(mode_context)
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
            updates = {
                **transition_mode(state, target_mode),
                **add_message(state, "assistant", final_response),
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Branch 2: New customer ───────────────────────────────────────
        # Create customer silently using pending_whatsapp_name (from Chatwoot sender.name)
        pending_name = state.get("pending_whatsapp_name")
        existing_id = state.get("customer_id")
        customer_id = existing_id or await self._create_customer(state, pending_name)

        self.logger.info(
            "GreetingMode: new customer | pending_name=%s | customer_id=%s | target_mode=%s",
            pending_name,
            customer_id,
            target_mode,
        )

        # If customer creation failed and there was no pre-existing ID, escalate
        if not customer_id and not existing_id:
            self.logger.error(
                "GreetingMode: customer creation returned None — escalating to support | phone=%s",
                state.get("customer_phone"),
            )
            return {
                **transition_mode(state, "ESCALATION"),
                **add_message(
                    state,
                    "assistant",
                    "Disculpá, estoy teniendo un problema técnico. Voy a derivarte con un agente. 🙏",
                ),
                "mode_context": {
                    **mode_context,
                    "escalation_reason": "customer_creation_failed",
                },
                "error_count": state.get("error_count", 0) + 1,
                "user_message": None,
            }

        fallback_response = _WELCOME_NEW
        response = await self._render_layered_response(
            state,
            mode_context,
            fallback_response=fallback_response,
            step_name="welcome",
            include_history=False,
        )
        final_response, disclosure_sent = self._maybe_prepend_intro(response, state)
        updates = {
            **transition_mode(state, target_mode),
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
