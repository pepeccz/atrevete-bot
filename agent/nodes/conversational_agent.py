"""
Conversational Agent Node - v3.0 Architecture.

This is the single node that handles ALL conversations using Claude Sonnet 4
with 7 consolidated tools. Replaces the hybrid Tier 1/Tier 2 architecture.

Handles everything:
- FAQs, greetings, service inquiries → query_info tool
- Customer identification → manage_customer tool
- Availability checking → check_availability tool
- Booking → book tool (delegates to BookingTransaction)
- Indecision → offer_consultation_tool
- Escalation → escalate_to_human tool

No transitions to transactional nodes. Claude orchestrates entire conversation.
"""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.prompts import load_maite_system_prompt, load_stylist_context
from agent.state.helpers import add_message
from agent.state.schemas import ConversationState
from agent.tools import (
    check_availability,
    book,
    escalate_to_human,
    get_customer_history,
    manage_customer,
    offer_consultation_tool,
    query_info,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)


def get_llm_with_tools() -> ChatAnthropic:
    """
    Get Claude LLM instance with 7 consolidated tools bound.

    Tools available (v3.0 consolidated):
    1. query_info: Unified information queries (services, FAQs, hours, policies)
    2. manage_customer: Unified customer management (get, create, update)
    3. get_customer_history: Customer appointment history
    4. check_availability: Calendar availability with natural date parsing
    5. book: Atomic booking via BookingTransaction handler
    6. offer_consultation_tool: Free consultation for indecisive customers
    7. escalate_to_human: Human escalation

    Returns:
        ChatAnthropic instance with 7 tools bound
    """
    settings = get_settings()

    llm = ChatAnthropic(
        model="claude-3-5-haiku-20241022",
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.3,
    )

    # Bind 7 consolidated tools for v3.0 architecture
    tools = [
        query_info,               # 1. Information queries (replaces 4 tools)
        manage_customer,          # 2. Customer management (replaces 3 tools)
        get_customer_history,     # 3. Customer history
        check_availability,       # 4. Availability checking (enhanced with natural dates)
        book,                     # 5. Atomic booking (replaces entire booking flow)
        offer_consultation_tool,  # 6. Free consultation offering
        escalate_to_human,        # 7. Human escalation
    ]

    llm_with_tools = llm.bind_tools(tools)

    logger.info("Claude LLM initialized with 7 consolidated tools (v3.0)")

    return llm_with_tools


async def execute_tool_call(tool_call: dict) -> str:
    """
    Execute a single tool call and return the result as a string.

    Args:
        tool_call: Tool call dict with 'name', 'args', and 'id' keys

    Returns:
        String representation of tool result (JSON or error message)
    """
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})

    logger.info(
        f"Executing tool: {tool_name}",
        extra={
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
    )

    # Map tool names to their implementations (7 tools)
    tool_map = {
        "query_info": query_info,
        "manage_customer": manage_customer,
        "get_customer_history": get_customer_history,
        "check_availability": check_availability,
        "book": book,
        "offer_consultation_tool": offer_consultation_tool,
        "escalate_to_human": escalate_to_human,
    }

    tool = tool_map.get(tool_name)

    if not tool:
        error_msg = f"Tool '{tool_name}' not found in tool map (available: {list(tool_map.keys())})"
        logger.error(error_msg)
        return error_msg

    try:
        # Execute tool asynchronously
        result = await tool.ainvoke(tool_args)

        logger.info(
            f"Tool {tool_name} executed successfully",
            extra={
                "tool_name": tool_name,
                "result_preview": str(result)[:200],
            }
        )

        # Convert result to string for LangChain ToolMessage
        import json
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
        else:
            return str(result)

    except Exception as e:
        error_msg = f"Error executing tool {tool_name}: {str(e)}"
        logger.error(
            error_msg,
            extra={
                "tool_name": tool_name,
                "tool_args": tool_args,
                "error": str(e),
            },
            exc_info=True
        )
        return error_msg


async def conversational_agent(state: ConversationState) -> dict[str, Any]:
    """
    Main conversational agent node using Claude Sonnet 4 with 7 consolidated tools.

    This single node handles ALL conversation via Claude's reasoning + tool calling.
    No explicit state transitions, no booking phases, no transactional nodes.

    Workflow:
    1. Build LangChain message history from state
    2. Add system prompt with Maite personality + stylist context
    3. Invoke Claude LLM with tools
    4. Execute tool calls if any
    5. Get final response from Claude
    6. Update state with assistant message

    Args:
        state: Current conversation state

    Returns:
        Updated state with assistant response added
    """
    conversation_id = state.get("conversation_id", "unknown")
    messages_history = state.get("messages", [])

    logger.info(
        f"Conversational agent (v3.0) invoked",
        extra={
            "conversation_id": conversation_id,
            "messages_count": len(messages_history),
        }
    )

    # Step 1: Build LangChain message history from state
    langchain_messages = []

    # Add system prompt
    system_prompt = load_maite_system_prompt()
    stylist_context = load_stylist_context()
    full_system_prompt = f"{system_prompt}\n\n{stylist_context}"

    langchain_messages.append(SystemMessage(content=full_system_prompt))

    # Convert state messages to LangChain format
    for msg in messages_history:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            langchain_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            langchain_messages.append(AIMessage(content=content))
        else:
            logger.warning(
                f"Unknown message role: {role}",
                extra={"conversation_id": conversation_id}
            )

    # Step 2: Get LLM with tools
    llm_with_tools = get_llm_with_tools()

    # Step 3: Invoke Claude LLM with tools (first pass)
    try:
        response = await llm_with_tools.ainvoke(langchain_messages)

        logger.info(
            f"Claude response received",
            extra={
                "conversation_id": conversation_id,
                "has_tool_calls": bool(response.tool_calls),
                "tool_calls_count": len(response.tool_calls) if response.tool_calls else 0,
            }
        )

    except Exception as e:
        logger.error(
            f"Error invoking Claude LLM",
            extra={
                "conversation_id": conversation_id,
                "error": str(e),
            },
            exc_info=True
        )

        # Return error message to user
        return add_message(
            state,
            "assistant",
            "Lo siento, he tenido un problema técnico. ¿Podrías repetir tu mensaje? 🌸"
        )

    # Step 4: Handle tool calls if any
    if response.tool_calls:
        logger.info(
            f"Executing {len(response.tool_calls)} tool call(s)",
            extra={
                "conversation_id": conversation_id,
                "tools": [tc["name"] for tc in response.tool_calls],
            }
        )

        # Add Claude's response with tool calls to message history
        langchain_messages.append(response)

        # Execute each tool call
        for tool_call in response.tool_calls:
            tool_result = await execute_tool_call(tool_call)

            # Add tool result to message history
            langchain_messages.append(
                ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call["id"]
                )
            )

        # Step 5: Get final response from Claude after tool execution
        try:
            final_response = await llm_with_tools.ainvoke(langchain_messages)

            logger.info(
                f"Claude final response received after tool execution",
                extra={
                    "conversation_id": conversation_id,
                    "response_preview": final_response.content[:100],
                }
            )

        except Exception as e:
            logger.error(
                f"Error invoking Claude LLM for final response",
                extra={
                    "conversation_id": conversation_id,
                    "error": str(e),
                },
                exc_info=True
            )

            # Return error message to user
            return add_message(
                state,
                "assistant",
                "Lo siento, he tenido un problema al procesar tu solicitud. ¿Podrías intentarlo de nuevo? 🌸"
            )

        assistant_response = final_response.content

    else:
        # No tool calls - use response content directly
        assistant_response = response.content

    # Step 6: Check for escalation trigger
    # If escalate_to_human was called, mark escalation in state
    if response.tool_calls:
        for tool_call in response.tool_calls:
            if tool_call["name"] == "escalate_to_human":
                logger.info(
                    f"Escalation detected in tool calls",
                    extra={
                        "conversation_id": conversation_id,
                        "reason": tool_call["args"].get("reason"),
                    }
                )
                # Mark escalation in state
                updated_state = add_message(state, "assistant", assistant_response)
                updated_state["escalation_triggered"] = True
                updated_state["escalation_reason"] = tool_call["args"].get("reason")
                updated_state["last_node"] = "conversational_agent"
                updated_state["updated_at"] = datetime.now(ZoneInfo("Europe/Madrid"))
                return updated_state

    # Step 7: Update state with assistant response
    updated_state = add_message(state, "assistant", assistant_response)
    updated_state["last_node"] = "conversational_agent"
    updated_state["updated_at"] = datetime.now(ZoneInfo("Europe/Madrid"))

    logger.info(
        f"Conversational agent completed",
        extra={
            "conversation_id": conversation_id,
            "response_preview": assistant_response[:100],
        }
    )

    return updated_state
