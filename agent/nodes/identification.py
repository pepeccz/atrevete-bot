"""
Customer identification nodes for LangGraph conversation flow.

This module contains nodes for:
- Identifying customers by phone number
- Greeting new customers with Maite persona
- Confirming customer names with fallback handling
"""

import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

from agent.state.helpers import add_message, format_llm_messages_with_summary
from agent.state.schemas import ConversationState
from agent.tools.customer_tools import create_customer, get_customer_by_phone, get_customer_history

logger = logging.getLogger(__name__)

# Initialize Claude LLM for name classification
llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)


async def identify_customer(state: ConversationState) -> dict[str, Any]:
    """
    Identify customer by phone number.

    Queries the database for a customer with the given phone number and updates
    the state with customer information if found.

    Args:
        state: Current conversation state containing customer_phone

    Returns:
        dict: State updates with customer info or is_returning_customer flag
    """
    conversation_id = state.get("conversation_id")
    phone = state.get("customer_phone")

    try:
        logger.info(
            f"Attempting to identify customer by phone",
            extra={"conversation_id": conversation_id, "phone": phone}
        )

        # Call CustomerTools to get customer (using .ainvoke for LangChain tools)
        customer_result = await get_customer_by_phone.ainvoke({"phone": phone})

        if customer_result and "error" not in customer_result:
            # Customer found - returning customer path
            logger.info(
                f"Customer identified: {customer_result['id']}",
                extra={"conversation_id": conversation_id, "customer_id": customer_result["id"]}
            )

            # Build full name, handling None last_name
            first_name = customer_result['first_name'] or ""
            last_name = customer_result['last_name'] or ""
            full_name = f"{first_name} {last_name}".strip() if last_name else first_name

            # Retrieve customer appointment history
            history_result = await get_customer_history.ainvoke({
                "customer_id": customer_result["id"],
                "limit": 5
            })

            # Extract appointment list from history result
            appointments = []
            if history_result and "error" not in history_result:
                appointments = history_result.get("appointments", [])
                logger.info(
                    f"Retrieved {len(appointments)} appointments for customer",
                    extra={"conversation_id": conversation_id, "customer_id": customer_result["id"]}
                )
            else:
                # Log warning if history retrieval failed, but don't block the flow
                logger.warning(
                    f"Failed to retrieve customer history, proceeding without history",
                    extra={"conversation_id": conversation_id, "customer_id": customer_result["id"]}
                )

            # Handle incomplete profile (missing last_name)
            if not customer_result.get("last_name"):
                logger.info(
                    f"Customer has incomplete profile (missing last_name)",
                    extra={"conversation_id": conversation_id, "customer_id": customer_result["id"]}
                )

            return {
                "customer_id": customer_result["id"],
                "customer_name": full_name,
                "is_returning_customer": True,
                "customer_identified": True,  # Skip name confirmation for returning customers
                "customer_history": appointments,
                "preferred_stylist_id": customer_result.get("preferred_stylist_id"),
            }
        else:
            # Customer not found
            logger.info(
                f"Customer not found for phone",
                extra={"conversation_id": conversation_id, "phone": phone}
            )

            return {
                "is_returning_customer": False,
            }

    except Exception as e:
        logger.error(
            f"Error in identify_customer: {e}",
            extra={"conversation_id": conversation_id, "phone": phone},
            exc_info=True
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
            "is_returning_customer": False,
        }


async def greet_returning_customer(state: ConversationState) -> dict[str, Any]:
    """
    Greet returning customer with personalized greeting.

    Generates a warm personalized greeting for returning customers using their
    first name and Maite's emoji.

    Args:
        state: Current conversation state

    Returns:
        dict: State updates with greeting message
    """
    conversation_id = state.get("conversation_id")
    customer_name = state.get("customer_name", "")
    customer_phone = state.get("customer_phone")

    try:
        # If customer_name is not set or is invalid, try to fetch from database
        if not customer_name or customer_name == "None" or customer_name.strip() == "":
            logger.info(
                f"Customer name not in state, fetching from database",
                extra={"conversation_id": conversation_id, "phone": customer_phone}
            )

            # Import here to avoid circular dependency
            from agent.tools.customer_tools import get_customer_by_phone

            # Fetch customer data
            customer_result = await get_customer_by_phone.ainvoke({"phone": customer_phone})

            if customer_result and "error" not in customer_result:
                # Build customer name properly
                first_name_db = customer_result.get('first_name') or ""
                last_name_db = customer_result.get('last_name') or ""
                customer_name = f"{first_name_db} {last_name_db}".strip() if last_name_db else first_name_db

                logger.info(
                    f"Fetched customer name from database: {customer_name}",
                    extra={"conversation_id": conversation_id}
                )

        # Extract first name from full customer name
        first_name = customer_name.split()[0] if customer_name and customer_name.strip() else "Cliente"

        logger.info(
            f"Greeting returning customer",
            extra={"conversation_id": conversation_id, "first_name": first_name}
        )

        # Generate personalized greeting for returning customer
        greeting_text = f"¡Hola, {first_name}! Soy Maite 🌸. ¿En qué puedo ayudarte hoy?"

        # Add greeting message to state using helper (with FIFO windowing)
        updated_state = add_message(state, "assistant", greeting_text)

        logger.info(
            f"Greeting sent to returning customer",
            extra={"conversation_id": conversation_id, "first_name": first_name}
        )

        return {
            "messages": updated_state["messages"],
            "updated_at": updated_state["updated_at"],
        }

    except Exception as e:
        logger.error(
            f"Error in greet_returning_customer: {e}",
            extra={"conversation_id": conversation_id},
            exc_info=True
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
        }


async def greet_new_customer(state: ConversationState) -> dict[str, Any]:
    """
    Greet new customer with Maite persona and request name confirmation.

    Generates a warm greeting message introducing Maite and asks for name
    confirmation based on WhatsApp metadata availability.

    Args:
        state: Current conversation state

    Returns:
        dict: State updates with greeting message and awaiting_name_confirmation flag
    """
    conversation_id = state.get("conversation_id")
    metadata = state.get("metadata", {})
    metadata_name = metadata.get("whatsapp_name", "")

    try:
        logger.info(
            f"Greeting new customer",
            extra={"conversation_id": conversation_id, "has_metadata_name": bool(metadata_name)}
        )

        # Check if metadata name is reliable (non-numeric, >2 chars)
        is_reliable_name = (
            metadata_name
            and len(metadata_name) > 2
            and not metadata_name.replace(" ", "").isdigit()
        )

        if is_reliable_name:
            # Greeting with name confirmation
            greeting_text = (
                f"¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. "
                f"Encantada de saludarte. ¿Me confirmas si tu nombre es {metadata_name}?"
            )
        else:
            # Greeting without metadata name - ask for name
            greeting_text = (
                "¡Hola! Soy **Maite, la asistenta virtual de Atrévete Peluquería** 🌸. "
                "Encantada de saludarte. ¿Me confirmas tu nombre para dirigirme a ti correctamente?"
            )

        # Add greeting message to state using helper (with FIFO windowing)
        updated_state = add_message(state, "assistant", greeting_text)

        logger.info(
            f"Greeting sent to new customer",
            extra={"conversation_id": conversation_id, "greeting_type": "with_name" if is_reliable_name else "without_name"}
        )

        return {
            "messages": updated_state["messages"],
            "updated_at": updated_state["updated_at"],
            "awaiting_name_confirmation": True,
        }

    except Exception as e:
        logger.error(
            f"Error in greet_new_customer: {e}",
            extra={"conversation_id": conversation_id},
            exc_info=True
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
        }


async def confirm_name(state: ConversationState) -> dict[str, Any]:
    """
    Confirm customer name from user response.

    Uses Claude LLM to classify the user's response as:
    - confirmed: User confirms the suggested name
    - different_name:{name}: User provides a different name
    - ambiguous: Response is unclear (triggers clarification or escalation)

    Args:
        state: Current conversation state with user's response

    Returns:
        dict: State updates with customer creation result or clarification request
    """
    conversation_id = state.get("conversation_id")
    phone = state.get("customer_phone")
    messages = state.get("messages", [])
    metadata = state.get("metadata", {})
    metadata_name = metadata.get("whatsapp_name", "")
    clarification_attempts = state.get("clarification_attempts", 0)

    try:
        # Extract most recent user message
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        if not user_messages:
            logger.warning(f"No user messages found in state", extra={"conversation_id": conversation_id})
            return {"error_count": state.get("error_count", 0) + 1}

        latest_user_message = user_messages[-1].content

        logger.info(
            f"Processing name confirmation response",
            extra={"conversation_id": conversation_id, "user_message": latest_user_message}
        )

        # Use Claude to classify the response
        # Different prompts depending on whether we have a metadata name to confirm
        if metadata_name:
            # User was asked to confirm a suggested name
            classification_prompt = f"""The user was asked to confirm if their name is "{metadata_name}".
Their response: "{latest_user_message}"

Classify the response:
- If confirmed (sí, correcto, exacto, afirmativo, etc.) → return "confirmed"
- If they provide a different name → return "different_name:{{extracted_name}}"
- If unclear or ambiguous → return "ambiguous"

Return ONLY the classification, nothing else."""
        else:
            # User was asked to provide their name directly
            classification_prompt = f"""The user was asked to provide their name.
Their response: "{latest_user_message}"

Classify the response:
- If they provide a clear name → return "different_name:{{extracted_name}}"
- If unclear or ambiguous → return "ambiguous"

Return ONLY the classification, nothing else."""

        # Format messages with conversation summary if present
        llm_messages = format_llm_messages_with_summary(state, classification_prompt)
        llm_response = await llm.ainvoke(llm_messages)
        classification = llm_response.content.strip()

        logger.info(
            f"Name classification result: {classification}",
            extra={"conversation_id": conversation_id}
        )

        # Handle confirmed name
        if classification.lower() == "confirmed":
            logger.info(f"Name confirmed, creating customer", extra={"conversation_id": conversation_id})

            # Extract first and last name from metadata_name
            name_parts = metadata_name.split(maxsplit=1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            # Create customer (using .ainvoke for LangChain tools)
            customer_result = await create_customer.ainvoke({
                "phone": phone,
                "first_name": first_name,
                "last_name": last_name
            })

            if customer_result and "error" not in customer_result:
                logger.info(
                    f"Customer created: {customer_result['id']}",
                    extra={"conversation_id": conversation_id, "customer_id": customer_result["id"]}
                )

                # Add confirmation message
                confirmation_msg = f"Perfecto, {first_name}! Gracias por confirmar. ¿En qué puedo ayudarte hoy?"
                updated_state = add_message(state, "assistant", confirmation_msg)

                # Build full name, handling None last_name
                full_name = f"{first_name} {last_name}".strip() if last_name and last_name != "None" else first_name

                return {
                    "customer_id": customer_result["id"],
                    "customer_name": full_name,
                    "customer_identified": True,
                    "awaiting_name_confirmation": False,
                    "messages": updated_state["messages"],
                    "updated_at": updated_state["updated_at"],
                }
            else:
                logger.error(
                    f"Failed to create customer: {customer_result}",
                    extra={"conversation_id": conversation_id}
                )
                return {"error_count": state.get("error_count", 0) + 1}

        # Handle different name provided
        elif classification.lower().startswith("different_name:"):
            corrected_name = classification.split(":", 1)[1].strip()
            logger.info(
                f"Different name provided: {corrected_name}",
                extra={"conversation_id": conversation_id}
            )

            # Extract first and last name from corrected name
            name_parts = corrected_name.split(maxsplit=1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            # Create customer with corrected name (using .ainvoke for LangChain tools)
            customer_result = await create_customer.ainvoke({
                "phone": phone,
                "first_name": first_name,
                "last_name": last_name
            })

            if customer_result and "error" not in customer_result:
                logger.info(
                    f"Customer created with corrected name: {customer_result['id']}",
                    extra={"conversation_id": conversation_id, "customer_id": customer_result["id"]}
                )

                # Add confirmation message
                confirmation_msg = f"Encantada de conocerte, {first_name}! ¿En qué puedo ayudarte hoy?"
                updated_state = add_message(state, "assistant", confirmation_msg)

                # Build full name, handling None last_name
                full_name = f"{first_name} {last_name}".strip() if last_name and last_name != "None" else first_name

                return {
                    "customer_id": customer_result["id"],
                    "customer_name": full_name,
                    "customer_identified": True,
                    "awaiting_name_confirmation": False,
                    "messages": updated_state["messages"],
                    "updated_at": updated_state["updated_at"],
                }
            else:
                logger.error(
                    f"Failed to create customer with corrected name: {customer_result}",
                    extra={"conversation_id": conversation_id}
                )
                return {"error_count": state.get("error_count", 0) + 1}

        # Handle ambiguous response
        elif classification.lower() == "ambiguous":
            new_attempts = clarification_attempts + 1
            logger.info(
                f"Ambiguous response, attempt {new_attempts}",
                extra={"conversation_id": conversation_id}
            )

            if new_attempts >= 2:
                # Escalate after 2 ambiguous attempts
                logger.warning(
                    f"Escalating due to repeated ambiguous responses",
                    extra={"conversation_id": conversation_id}
                )

                # Add escalation message to state
                escalation_msg = AIMessage(
                    content="Disculpa, voy a conectarte con una persona de nuestro equipo que podrá ayudarte mejor."
                )
                updated_messages = list(messages)
                updated_messages.append(escalation_msg)

                return {
                    "escalated": True,
                    "escalation_reason": "ambiguity",
                    "clarification_attempts": new_attempts,
                    "messages": updated_messages,
                }
            else:
                # Request clarification
                clarification_msg = AIMessage(
                    content="Disculpa, no entendí bien. ¿Podrías confirmar tu nombre completo?"
                )
                updated_messages = list(messages)
                updated_messages.append(clarification_msg)

                return {
                    "clarification_attempts": new_attempts,
                    "messages": updated_messages,
                }

        # Unexpected classification result
        else:
            logger.error(
                f"Unexpected classification result: {classification}",
                extra={"conversation_id": conversation_id}
            )
            return {"error_count": state.get("error_count", 0) + 1}

    except Exception as e:
        logger.error(
            f"Error in confirm_name: {e}",
            extra={"conversation_id": conversation_id},
            exc_info=True
        )
        return {
            "error_count": state.get("error_count", 0) + 1,
        }
