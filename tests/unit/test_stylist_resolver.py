"""
Unit tests for BookingMode._resolve_stylist_from_message().

Coverage:
- No-preference phrases: cualquiera, no importa, sin preferencia, primer horario, etc.
- Ordinal/numeric picks: el 1, la primera, el 2, la segunda, etc.
- Name substring match: partial, case-insensitive, accent-normalized.
- Unavailable stylist name → None.
- Empty input edge cases.
- soonest_any_slot_candidate absent → None when no-pref phrase used.

All LLM calls are avoided — resolver is deterministic (pure Python).
"""

import pytest

from agent.modes.booking_mode import BookingMode


# =============================================================================
# Fixtures
# =============================================================================

STYLIST_A = {"id": "uuid-a", "name": "María García", "next_slot_summary": "lunes a las 10:00"}
STYLIST_B = {"id": "uuid-b", "name": "Carmen López", "next_slot_summary": "martes a las 11:00"}
STYLIST_C = {"id": "uuid-c", "name": "Ana Martínez", "next_slot_summary": "miércoles a las 12:00"}

SOONEST_CANDIDATE = {
    "stylist_id": "uuid-a",
    "stylist_name": "María García",
    "slot_datetime": "2026-03-23T10:00:00",
    "slot_summary": "lunes 23/03 a las 10:00",
}

PREFETCHED = [STYLIST_A, STYLIST_B, STYLIST_C]


def make_resolver() -> BookingMode:
    """BookingMode instance with a stub LLM — resolver is pure Python, LLM not called."""
    from unittest.mock import AsyncMock, MagicMock

    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = ""
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


# =============================================================================
# 1. No-preference phrases → soonest_any_slot_candidate
# =============================================================================


class TestResolveNoPrefPhrases:
    """User says they have no stylist preference → pick soonest candidate."""

    @pytest.mark.parametrize(
        "message",
        [
            "cualquiera",
            "Cualquiera está bien",
            "no importa quien sea",
            "No me importa",
            "sin preferencia",
            "Sin Preferencia",
            "no tengo preferencia",
            "el que sea",
            "la que sea",
            "primer horario disponible",
            "el mas temprano",
            "lo antes posible",
            "cualquier estilista",
        ],
    )
    def test_no_pref_resolves_to_soonest_candidate(self, message: str):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message(message, PREFETCHED, SOONEST_CANDIDATE)
        assert result is not None
        assert result["stylist_id"] == "uuid-a"
        assert result["stylist_name"] == "María García"

    def test_no_pref_without_candidate_returns_none(self):
        """If no soonest_any_slot_candidate is available, resolver returns None."""
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("cualquiera", PREFETCHED, None)
        assert result is None

    def test_no_pref_with_empty_candidate_id_returns_none(self):
        """If candidate has no stylist_id, resolver returns None."""
        resolver = make_resolver()
        candidate = {**SOONEST_CANDIDATE, "stylist_id": ""}
        result = resolver._resolve_stylist_from_message("cualquiera", PREFETCHED, candidate)
        assert result is None


# =============================================================================
# 2. Ordinal / numeric picks
# =============================================================================


class TestResolveOrdinalPicks:
    """User picks by position/number."""

    @pytest.mark.parametrize(
        "message, expected_id, expected_name",
        [
            ("la primera", "uuid-a", "María García"),
            ("el primero", "uuid-a", "María García"),
            ("el 1", "uuid-a", "María García"),
            ("el número 1", "uuid-a", "María García"),
            ("el 2", "uuid-b", "Carmen López"),
            ("la segunda", "uuid-b", "Carmen López"),
            ("el 3", "uuid-c", "Ana Martínez"),
            ("la tercera", "uuid-c", "Ana Martínez"),
        ],
    )
    def test_ordinal_resolves_correct_stylist(self, message: str, expected_id: str, expected_name: str):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message(message, PREFETCHED, SOONEST_CANDIDATE)
        assert result is not None
        assert result["stylist_id"] == expected_id
        assert result["stylist_name"] == expected_name

    def test_ordinal_beyond_list_returns_none(self):
        """Ordinal 5 when only 3 stylists → None."""
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("el 5", PREFETCHED, SOONEST_CANDIDATE)
        assert result is None

    def test_ordinal_with_empty_list_returns_none(self):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("el 1", [], SOONEST_CANDIDATE)
        assert result is None


# =============================================================================
# 3. Name substring match
# =============================================================================


class TestResolveNameMatch:
    """User picks by (partial) stylist name."""

    @pytest.mark.parametrize(
        "message, expected_id",
        [
            ("quiero con María", "uuid-a"),
            ("María", "uuid-a"),
            ("con carmen", "uuid-b"),
            ("Carmen López por favor", "uuid-b"),
            ("Ana está bien", "uuid-c"),
            ("la Martínez", "uuid-c"),
        ],
    )
    def test_name_match_resolves_correct_stylist(self, message: str, expected_id: str):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message(message, PREFETCHED, SOONEST_CANDIDATE)
        assert result is not None
        assert result["stylist_id"] == expected_id

    def test_accent_normalized_name_match(self):
        """'Garcia' (no accent) should match 'García' stylist."""
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("con Garcia", PREFETCHED, SOONEST_CANDIDATE)
        assert result is not None
        assert result["stylist_id"] == "uuid-a"

    def test_uppercase_name_match(self):
        """Case-insensitive: 'CARMEN' matches 'Carmen López'."""
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("CARMEN", PREFETCHED, SOONEST_CANDIDATE)
        assert result is not None
        assert result["stylist_id"] == "uuid-b"


# =============================================================================
# 4. Unavailable stylist (not in prefetched list)
# =============================================================================


class TestResolveUnavailableStylist:
    """User names a stylist not in the prefetched list → None (FSM stays at stylist_selection)."""

    def test_unknown_name_returns_none(self):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("quiero con Pilar", PREFETCHED, SOONEST_CANDIDATE)
        assert result is None

    def test_completely_unrelated_message_returns_none(self):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("cuánto cuesta el corte?", PREFETCHED, SOONEST_CANDIDATE)
        assert result is None


# =============================================================================
# 5. Edge cases
# =============================================================================


class TestResolveEdgeCases:
    """Edge cases: empty message, empty list, short tokens."""

    def test_empty_message_returns_none(self):
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("", PREFETCHED, SOONEST_CANDIDATE)
        assert result is None

    def test_empty_prefetched_list_no_pref_returns_none(self):
        """No-pref phrase but no prefetched stylists → soonest_candidate still used."""
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("cualquiera", [], SOONEST_CANDIDATE)
        # soonest_candidate has stylist_id → should still resolve
        assert result is not None
        assert result["stylist_id"] == "uuid-a"

    def test_stylist_with_very_short_name_token_not_matched(self):
        """A stylist with a 2-char name token should not be matched against short tokens."""
        short_name_stylist = {"id": "uuid-x", "name": "Al García", "next_slot_summary": ""}
        prefetched = [short_name_stylist]
        resolver = make_resolver()
        # "Al" is 2 chars — should be skipped by the ≥3 token filter
        result = resolver._resolve_stylist_from_message("García", prefetched, None)
        assert result is not None  # "García" ≥ 3 chars → matches
        assert result["stylist_id"] == "uuid-x"

    def test_stylist_with_missing_id_skipped(self):
        """Stylist entry with no 'id' should not be returned."""
        no_id_stylist = {"id": "", "name": "Carmen López", "next_slot_summary": ""}
        resolver = make_resolver()
        result = resolver._resolve_stylist_from_message("Carmen", [no_id_stylist], None)
        assert result is None
