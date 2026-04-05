"""
Agent Tools for v4.0 Architecture (4-tool design).

This module exports 4 tools for the conversational agent:
1. check_availability - Calendar availability checking with natural date parsing
2. book - Atomic booking transaction (creates customer + appointment atomically)
3. manage_appointments - View, cancel, or reschedule existing appointments
4. escalate - Human escalation for edge cases

Architecture:
- Tier 1: Conversational agent uses these 4 tools
- Utilities: date_parser, service_resolver, validators (not exposed as tools)
"""

from agent.tools.availability_tools import check_availability
from agent.tools.booking_tools import book
from agent.tools.escalation_tools import escalate
from agent.tools.manage_appointments_tool import manage_appointments

__all__ = [
    "check_availability",
    "book",
    "manage_appointments",
    "escalate",
]
