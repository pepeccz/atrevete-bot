"""
Agent Tools for v3.1 Architecture (Consolidated + Enhanced).

This module exports 8 consolidated tools for the conversational agent:
1. query_info - Unified information queries (services, FAQs, hours, policies)
2. search_services - Fuzzy search for specific services (NEW in v3.1)
3. manage_customer - Unified customer management (get, create, update)
4. get_customer_history - Customer appointment history
5. check_availability - Calendar availability checking with natural date parsing
6. find_next_available - Automatic multi-date availability search
7. book - Atomic booking transaction (delegates to BookingTransaction)
8. escalate_to_human - Human escalation for edge cases

Reduced from 13 tools (v2) to 8 tools (v3.1).

Architecture:
- Tier 1: Conversational agent (Claude Haiku 4.5) uses these tools
- Tier 2: Transactional nodes delegate to handlers (BookingTransaction)
- Utilities: date_parser, service_resolver, validators (not exposed as tools)
"""

from agent.tools.availability_tools import check_availability, find_next_available
from agent.tools.booking_tools import book
from agent.tools.customer_tools import get_customer_history, manage_customer
from agent.tools.escalation_tools import escalate_to_human
from agent.tools.info_tools import list_stylists, query_info
from agent.tools.search_services import search_services

__all__ = [
    # Information tools (3 tools: general queries + search + stylists)
    "search_services",  # NEW: Fuzzy search for specific services (solves 47-service overflow)
    "list_stylists",  # NEW: List active stylists from database
    # Customer tools (2 tools: 1 consolidated + 1 specialized)
    "manage_customer",  # Replaces: get_customer_by_phone, create_customer, update_customer_name
    "get_customer_history",  # Kept separate (different use case: querying appointments)
    # Availability tools (2 tools: single-date + multi-date search)
    "check_availability",  # Enhanced with parse_natural_date + validate_3_day_rule
    "find_next_available",  # Automatic search across multiple dates (v3.1)
    # Booking tools (1 atomic tool)
    "book",  # Replaces entire booking flow with atomic transaction
    # Escalation tools (1 tool for human handoff)
    "escalate_to_human",  # Escalates to human support
]
