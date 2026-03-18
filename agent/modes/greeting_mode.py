"""
Greeting Mode — v6.0 Mode-Based Architecture (customer-name-handling refactor).

Handles lightweight first contact for low-intent greetings. This mode NEVER
extracts or mentions the customer's name. Customer creation uses
`pending_whatsapp_name` (from Chatwoot sender.name) silently.

Flow:
1. If customer already exists (returning): warm name-free greeting → GENERAL
2. If new customer: create customer silently with sender_name → warm name-free greeting → GENERAL

NO name extraction from message text. NO name in any response.
"""

import logging

from agent.tools.customer_tools import manage_customer

from agent.modes.base import FIRST_TURN_INTRO, BaseModeNode
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState, transition_mode

logger = logging.getLogger(__name__)

# Pre-defined greeting messages (ALL name-free)
_WELCOME_NEW = f"{FIRST_TURN_INTRO} ¿En qué puedo ayudarte hoy?"
_WELCOME_RETURNING = "¡Hola de nuevo! 😊 ¿En qué puedo ayudarte hoy?"


class GreetingMode(BaseModeNode):
    """
    Mode node for first-contact greetings.

    Responsibilities:
    - Send a warm welcome on genuine greeting turns (WITHOUT using customer name)
    - Create customer record silently using sender_name from Chatwoot
    - Hand off to GENERAL after the greeting response
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
        if customer_name:
            self.logger.info(
                "GreetingMode: returning customer (name=%s), transitioning to GENERAL",
                customer_name,
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
                **transition_mode(state, "GENERAL"),
                **add_message(state, "assistant", final_response),
                "user_message": None,
            }
            if disclosure_sent:
                updates["ai_disclosure_sent"] = True
            return updates

        # ── Branch 2: New customer ───────────────────────────────────────
        # Create customer silently using pending_whatsapp_name (from Chatwoot sender.name)
        pending_name = state.get("pending_whatsapp_name")
        customer_id = state.get("customer_id") or await self._create_customer(
            state, pending_name
        )

        self.logger.info(
            "GreetingMode: new customer | pending_name=%s | customer_id=%s",
            pending_name,
            customer_id,
        )

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
            **transition_mode(state, "GENERAL"),
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

        # Validate: response must NOT contain the customer's name
        customer_name = state.get("customer_name") or state.get("pending_whatsapp_name")
        if response_text and customer_name:
            if customer_name.lower() in response_text.lower():
                self.logger.warning(
                    "GreetingMode: LLM leaked customer name in response, using fallback"
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
