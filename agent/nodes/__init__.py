"""
LangGraph nodes for conversation flow.

This package contains all node functions that process conversation state
and implement business logic for the booking agent.
"""

from agent.nodes.greeting import greet_customer
from agent.nodes.identification import (
    confirm_name,
    greet_new_customer,
    greet_returning_customer,
    identify_customer,
)
from agent.nodes.classification import extract_intent
from agent.nodes.summarization import summarize_conversation
from agent.nodes.faq import answer_faq, detect_faq_intent
from agent.nodes.faq_generation import fetch_faq_context, generate_personalized_faq_response
from agent.nodes.availability_nodes import check_availability
from agent.nodes.pack_suggestion_nodes import suggest_pack, handle_pack_response

__all__ = [
    "greet_customer",
    "identify_customer",
    "greet_new_customer",
    "greet_returning_customer",
    "confirm_name",
    "extract_intent",
    "summarize_conversation",
    "answer_faq",
    "detect_faq_intent",
    "fetch_faq_context",
    "generate_personalized_faq_response",
    "check_availability",
    "suggest_pack",
    "handle_pack_response",
]
