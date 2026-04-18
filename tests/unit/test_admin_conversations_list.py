"""Unit tests for Commit 2 — admin list endpoint reads sender_name from metadata.

Tests that the admin GET /conversations list:
1. Returns the customer's full name when customer_id is set.
2. Returns metadata sender_name when customer_id is NULL.
3. Returns "Desconocido" when customer_id is NULL AND metadata has no sender_name.
4. Returns started_at / ended_at from DB rows (not derived from messages).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.routes.admin import _conversation_display_name, _resolve_conversation_list_item


# ============================================================================
# Tests for _conversation_display_name helper
# ============================================================================


class TestConversationDisplayName:
    """Tests for the helper that resolves a display name for a conversation row."""

    def test_customer_full_name_when_customer_linked(self):
        """When customer is set, return 'first_name last_name'."""
        customer = MagicMock()
        customer.first_name = "María"
        customer.last_name = "García"

        row = MagicMock()
        row.customer = customer
        row.metadata_ = {}

        result = _conversation_display_name(row)
        assert result == "María García"

    def test_customer_first_name_only_when_no_last_name(self):
        """When customer has no last_name, return first_name only."""
        customer = MagicMock()
        customer.first_name = "Ana"
        customer.last_name = None

        row = MagicMock()
        row.customer = customer
        row.metadata_ = {}

        result = _conversation_display_name(row)
        assert result == "Ana"

    def test_sender_name_from_metadata_when_no_customer(self):
        """When customer is None, return metadata_.sender_name."""
        row = MagicMock()
        row.customer = None
        row.metadata_ = {"sender_name": "Carlos Fernández"}

        result = _conversation_display_name(row)
        assert result == "Carlos Fernández"

    def test_desconocido_when_no_customer_and_no_metadata(self):
        """When customer is None and metadata has no sender_name, return 'Desconocido'."""
        row = MagicMock()
        row.customer = None
        row.metadata_ = {}

        result = _conversation_display_name(row)
        assert result == "Desconocido"

    def test_desconocido_when_metadata_sender_name_is_empty_string(self):
        """When sender_name is an empty string, return 'Desconocido'."""
        row = MagicMock()
        row.customer = None
        row.metadata_ = {"sender_name": ""}

        result = _conversation_display_name(row)
        assert result == "Desconocido"

    def test_desconocido_when_no_customer_and_metadata_is_none(self):
        """When customer is None and metadata_ is None, return 'Desconocido'."""
        row = MagicMock()
        row.customer = None
        row.metadata_ = None

        result = _conversation_display_name(row)
        assert result == "Desconocido"


# ============================================================================
# Tests for _resolve_conversation_list_item helper
# ============================================================================


class TestResolveConversationListItem:
    """Tests for the helper that converts a DB row to a dict for the list response."""

    def _make_row(
        self,
        conversation_id: str = "conv-001",
        customer=None,
        metadata_: dict | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        message_count: int = 5,
        summary: str | None = None,
    ):
        row = MagicMock()
        row.id = uuid4()
        row.conversation_id = conversation_id
        row.customer_id = customer.id if customer else None
        row.customer = customer
        row.metadata_ = metadata_ if metadata_ is not None else {}
        row.started_at = started_at
        row.ended_at = ended_at
        row.message_count = message_count
        row.summary = summary
        row.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        return row

    def test_customer_name_from_linked_customer(self):
        """Row with customer → customer_name = full name."""
        customer = MagicMock()
        customer.id = uuid4()
        customer.first_name = "Lucía"
        customer.last_name = "Martínez"

        row = self._make_row(customer=customer)
        item = _resolve_conversation_list_item(row)

        assert item["customer_name"] == "Lucía Martínez"

    def test_customer_name_from_metadata_sender_name(self):
        """Row with no customer but metadata sender_name → uses metadata."""
        row = self._make_row(metadata_={"sender_name": "Pedro Sánchez"})
        item = _resolve_conversation_list_item(row)

        assert item["customer_name"] == "Pedro Sánchez"

    def test_customer_name_desconocido_when_empty(self):
        """Row with no customer and empty metadata → 'Desconocido'."""
        row = self._make_row(metadata_={})
        item = _resolve_conversation_list_item(row)

        assert item["customer_name"] == "Desconocido"

    def test_started_at_from_db(self):
        """started_at in list item comes from DB row, not message timestamps."""
        ts = datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
        row = self._make_row(started_at=ts)
        item = _resolve_conversation_list_item(row)

        assert item["started_at"] == ts.isoformat()

    def test_ended_at_from_db(self):
        """ended_at in list item comes from DB row."""
        ts = datetime(2024, 6, 15, 11, 0, tzinfo=timezone.utc)
        row = self._make_row(ended_at=ts)
        item = _resolve_conversation_list_item(row)

        assert item["ended_at"] == ts.isoformat()

    def test_none_timestamps_become_none(self):
        """None timestamps are serialized as None (not empty string)."""
        row = self._make_row(started_at=None, ended_at=None)
        item = _resolve_conversation_list_item(row)

        assert item["started_at"] is None
        assert item["ended_at"] is None

    def test_source_is_db(self):
        """source field is always 'db' for DB-sourced items."""
        row = self._make_row()
        item = _resolve_conversation_list_item(row)

        assert item["source"] == "db"
