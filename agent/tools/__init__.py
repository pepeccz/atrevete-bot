"""
Agent Tools for v3.0 Architecture (Consolidated).

This module exports only 7 consolidated tools for the conversational agent:
1. query_info - Unified information queries (services, FAQs, hours, policies)
2. manage_customer - Unified customer management (get, create, update)
3. get_customer_history - Customer appointment history
4. check_availability - Calendar availability checking with natural date parsing
5. book - Atomic booking transaction (delegates to BookingTransaction)
6. offer_consultation_tool - Free consultation offering for indecisive customers
7. escalate_to_human - Human escalation for edge cases

Reduced from 13 tools (v2) to 7 tools (v3) - 46% reduction in tool count.

Architecture:
- Tier 1: Conversational agent (Claude Sonnet 4) uses these tools
- Tier 2: Transactional nodes delegate to handlers (BookingTransaction)
- Utilities: date_parser, service_resolver, validators (not exposed as tools)
"""

from agent.tools.availability_tools import check_availability
from agent.tools.booking_tools import book
from agent.tools.consultation_tools import offer_consultation_tool
from agent.tools.customer_tools import get_customer_history, manage_customer
from agent.tools.escalation_tools import escalate_to_human
from agent.tools.info_tools import query_info

__all__ = [
    # Information tools (1 consolidated tool)
    "query_info",  # Replaces: get_services, get_faqs, get_business_hours, get_payment_policies
    # Customer tools (2 tools: 1 consolidated + 1 specialized)
    "manage_customer",  # Replaces: get_customer_by_phone, create_customer, update_customer_name
    "get_customer_history",  # Kept separate (different use case: querying appointments)
    # Availability tools (1 tool with natural date parsing)
    "check_availability",  # Enhanced with parse_natural_date + validate_3_day_rule
    # Booking tools (1 atomic tool)
    "book",  # Replaces entire booking flow with atomic transaction
    # Consultation tools (1 tool for indecision handling)
    "offer_consultation_tool",  # Offers free 15-min consultation
    # Escalation tools (1 tool for human handoff)
    "escalate_to_human",  # Escalates to human support
]
