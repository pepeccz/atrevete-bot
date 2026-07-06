"""Unit tests for Commit 2 — admin list endpoint reads sender_name from metadata.

Tests that the admin GET /conversations list:
1. Returns the customer's full name when customer_id is set.
2. Returns metadata sender_name when customer_id is NULL.
3. Returns "Desconocido" when customer_id is NULL AND metadata has no sender_name.
4. Returns started_at / ended_at from DB rows (not derived from messages).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

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
        row.created_at = datetime(2024, 1, 1, tzinfo=UTC)
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
        ts = datetime(2024, 6, 15, 10, 30, tzinfo=UTC)
        row = self._make_row(started_at=ts)
        item = _resolve_conversation_list_item(row)

        assert item["started_at"] == ts.isoformat()

    def test_ended_at_from_db(self):
        """ended_at in list item comes from DB row."""
        ts = datetime(2024, 6, 15, 11, 0, tzinfo=UTC)
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

    # -----------------------------------------------------------------------
    # C3: escalation signal — filter=escalated join-key correctness
    # -----------------------------------------------------------------------

    def test_is_escalated_false_when_no_map(self):
        """is_escalated is False when escalated_conv_map is None."""
        row = self._make_row(conversation_id="42")
        item = _resolve_conversation_list_item(row, escalated_conv_map=None)

        assert item["is_escalated"] is False

    def test_is_escalated_false_when_chatwoot_id_not_in_map(self):
        """is_escalated is False when conversation_id is absent from map — UUID PK never matches."""
        row = self._make_row(conversation_id="42")
        # Keying the map on str(row.id) (UUID PK) must NOT match — this would reproduce
        # the old bug where the wrong key was used.
        wrong_map = {
            str(row.id): {
                "escalation_id": "esc-1",
                "escalation_reason": "test",
                "escalation_source": "manual",
                "escalation_triggered_at": None,
            }
        }
        item = _resolve_conversation_list_item(row, escalated_conv_map=wrong_map)

        # The old (broken) code keyed on str(row.id); after the fix this must be False.
        assert item["is_escalated"] is False

    def test_is_escalated_true_when_chatwoot_id_matches(self):
        """is_escalated is True when escalated_conv_map is keyed by Chatwoot numeric ID string."""
        row = self._make_row(conversation_id="42")
        esc_map = {
            "42": {
                "escalation_id": "esc-uuid-1",
                "escalation_reason": "Manual takeover",
                "escalation_source": "manual",
                "escalation_triggered_at": "2024-06-01T10:00:00+00:00",
            }
        }
        item = _resolve_conversation_list_item(row, escalated_conv_map=esc_map)

        assert item["is_escalated"] is True
        assert item["escalation_source"] == "manual"
        assert item["escalation_reason"] == "Manual takeover"
        assert item["escalation_triggered_at"] == "2024-06-01T10:00:00+00:00"

    def test_escalated_filter_counts_match_escalated_rows(self):
        """Batch: counts['escalated'] equals the number of rows that have is_escalated=True."""
        esc_map = {
            "10": {
                "escalation_id": "e1",
                "escalation_reason": "r1",
                "escalation_source": "fallback",
                "escalation_triggered_at": None,
            },
            "20": {
                "escalation_id": "e2",
                "escalation_reason": "r2",
                "escalation_source": "auto_error",
                "escalation_triggered_at": None,
            },
        }

        rows = [
            self._make_row(conversation_id="10"),  # escalated
            self._make_row(conversation_id="20"),  # escalated
            self._make_row(conversation_id="99"),  # NOT escalated
        ]

        items = [_resolve_conversation_list_item(r, escalated_conv_map=esc_map) for r in rows]
        escalated_items = [i for i in items if i["is_escalated"]]

        assert len(escalated_items) == 2
        assert all(i["is_escalated"] for i in escalated_items)
        # Non-escalated row must not expose escalation fields
        non_esc = next(i for i in items if not i["is_escalated"])
        assert "escalation_id" not in non_esc

    # -----------------------------------------------------------------------
    # PR-1 (inbox-reliability): batched unread_message_count wiring
    # -----------------------------------------------------------------------

    def test_unread_count_wired_from_map(self):
        """unread_message_count is read from unread_map keyed by row.id (UUID PK)."""
        row = self._make_row(conversation_id="55")
        unread_map = {row.id: 3}

        item = _resolve_conversation_list_item(row, unread_map=unread_map)

        assert item["unread_message_count"] == 3

    def test_unread_count_defaults_to_zero_when_row_not_in_map(self):
        """A row absent from unread_map (no unread messages) defaults to 0."""
        row = self._make_row(conversation_id="56")
        unread_map = {uuid4(): 7}  # keyed to a different conversation's row.id

        item = _resolve_conversation_list_item(row, unread_map=unread_map)

        assert item["unread_message_count"] == 0

    def test_unread_count_defaults_to_zero_when_no_map_provided(self):
        """Existing callers that omit unread_map keep the additive-default-None behavior."""
        row = self._make_row(conversation_id="57")

        item = _resolve_conversation_list_item(row)

        assert item["unread_message_count"] == 0
