"""
Tests for conversation_flow.py.

NOTE: _extract_suggested_name was removed in the customer-name-handling refactor.
Names are now sourced from Chatwoot sender.name, not extracted from message text.
"""

import pytest

from agent.graphs.conversation_flow import check_customer_exists


# Placeholder — the old _extract_suggested_name tests are no longer applicable.
# New tests for router Rule 4 (is_first_interaction guard) are in
# tests/unit/test_routing.py.
