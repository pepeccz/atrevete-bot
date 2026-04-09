"""
Agent Tools for v6.0 Architecture (3-tool design).

This module exports 3 tools for the conversational agent:
1. check_availability - Calendar availability checking with natural date parsing
2. book - Atomic booking transaction (creates customer + appointment atomically)
3. manage_appointments - View, cancel, or reschedule existing appointments

Architecture:
- Tier 1: Conversational agent uses these 3 tools
- Utilities: date_parser, service_resolver, validators (not exposed as tools)
- Escalation: handled directly by EscalationMode via perform_escalation()
"""

from agent.tools.availability_tools import check_availability
from agent.tools.booking_tools import book
from agent.tools.manage_appointments_tool import manage_appointments

__all__ = [
    "check_availability",
    "book",
    "manage_appointments",
]
