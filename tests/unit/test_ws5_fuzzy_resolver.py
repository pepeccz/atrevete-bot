"""
WS-5: Unit tests for agent/utils/fuzzy_resolver.py

Coverage:
- normalize_spanish(): strips articles, prepositions, accents
- resolve_from_options(): all 5 strategies + threshold guard
- resolve_time_slot(): time pattern matching
- resolve_ordinal(): digit and Spanish ordinal words
- Tool integration: _resolve_service_by_name / _resolve_stylist_by_name fuzzy fallback
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.utils.fuzzy_resolver import (
    Match,
    normalize_spanish,
    resolve_from_options,
    resolve_time_slot,
    resolve_ordinal,
)


# =============================================================================
# normalize_spanish()
# =============================================================================


class TestNormalizeSpanish:
    """normalize_spanish() strips articles, prepositions, and accents."""

    def test_strips_article_las(self):
        assert normalize_spanish("las balayage") == "balayage"

    def test_strips_article_la(self):
        assert normalize_spanish("la primera") == "primera"

    def test_strips_preposition_con(self):
        assert normalize_spanish("con Ana") == "ana"

    def test_strips_multiple_words(self):
        result = normalize_spanish("el balayage de la tarde")
        # "el", "de", "la" stripped as standalone tokens → "balayage tarde"
        # Note: "de" as substring of "tarde" is fine; we check it was removed as a word
        tokens = result.split()
        assert "el" not in tokens
        assert "de" not in tokens
        assert "la" not in tokens
        assert "balayage" in result

    def test_strips_accents(self):
        result = normalize_spanish("Balayagé")
        assert "é" not in result
        assert "e" in result

    def test_lowercases(self):
        assert normalize_spanish("Balayage") == "balayage"
        assert normalize_spanish("ANA") == "ana"

    def test_empty_string(self):
        assert normalize_spanish("") == ""

    def test_no_change_needed(self):
        assert normalize_spanish("corte") == "corte"


# =============================================================================
# resolve_from_options() — strategy tests
# =============================================================================


class TestResolveFromOptions:
    """resolve_from_options() applies strategies in order."""

    OPTIONS = ["Balayage", "Corte", "Mechas", "Peinado Extra", "Ana Maria", "Ana"]

    def test_exact_match(self):
        result = resolve_from_options("Balayage", self.OPTIONS)
        assert result is not None
        assert result.value == "Balayage"
        assert result.strategy == "exact"
        assert result.confidence == 1.0

    def test_exact_match_case_insensitive(self):
        result = resolve_from_options("balayage", self.OPTIONS)
        assert result is not None
        assert result.value == "Balayage"
        assert result.strategy == "exact"

    def test_normalized_contains_article(self):
        """'las balayage' → 'las' stripped → 'balayage' matches 'Balayage' exactly or via contains."""
        result = resolve_from_options("las balayage", self.OPTIONS)
        assert result is not None
        assert result.value == "Balayage"
        # After normalization "las balayage" → "balayage" = "balayage" (exact or contains is fine)
        assert result.strategy in ("exact", "normalized_contains", "prefix")

    def test_normalized_contains_preposition(self):
        """'con Ana' → 'con' stripped → 'ana' matches 'Ana' via some strategy."""
        result = resolve_from_options("con Ana", ["Ana", "Marta", "Victor"])
        assert result is not None
        assert result.value == "Ana"

    def test_fuzzy_typo(self):
        """'balayagee' → matches 'Balayage' via normalized_contains or fuzzy_ratio."""
        result = resolve_from_options("balayagee", ["Balayage", "Corte"])
        assert result is not None
        assert result.value == "Balayage"
        # normalized_contains matches "balayage" in "balayagee", which is even better than fuzzy
        assert result.strategy in ("normalized_contains", "prefix", "fuzzy_ratio")
        assert result.confidence >= 0.75

    def test_below_threshold_returns_none(self):
        """'zzz' → no match above threshold."""
        result = resolve_from_options("zzz", ["Balayage", "Corte"])
        assert result is None

    def test_empty_input_returns_none(self):
        assert resolve_from_options("", ["Balayage"]) is None

    def test_empty_options_returns_none(self):
        assert resolve_from_options("Balayage", []) is None

    def test_custom_threshold(self):
        """Custom threshold affects only fuzzy_ratio. Exact/contains strategies still match."""
        # "balayagee" contains "balayage" (normalized_contains) — threshold doesn't affect it.
        # To test threshold isolation, use a pure typo that won't normalized_contains-match.
        # "baaayage" vs "Balayage" — no substring containment, only fuzzy
        result_default = resolve_from_options("baaayage", ["Balayage"], threshold=0.75)
        result_strict = resolve_from_options("baaayage", ["Balayage"], threshold=0.99)
        # With strict threshold, fuzzy match should fail
        if result_default is not None:
            # This input matches at some confidence — verify strict threshold rejects it
            assert result_strict is None or result_strict.confidence >= 0.99

    def test_key_fn_applied(self):
        """key_fn extracts comparison key from structured options."""
        options = [{"name": "Balayage"}, {"name": "Corte"}]
        result = resolve_from_options(
            "las balayage",
            options,
            key_fn=lambda o: o["name"],
        )
        assert result is not None
        assert result.value == {"name": "Balayage"}

    def test_prefix_strategy(self):
        """'peinado' matches 'Peinado Extra' via prefix."""
        result = resolve_from_options("peinado", ["Peinado Extra", "Corte"])
        assert result is not None
        assert result.value == "Peinado Extra"
        assert result.strategy in ("exact", "normalized_contains", "prefix")

    def test_stylist_with_double_name(self):
        """'Ana Maria' found before 'Ana' when options include both."""
        result = resolve_from_options("Ana Maria", ["Marta", "Ana Maria", "Ana"])
        assert result is not None
        assert result.value == "Ana Maria"

    def test_accented_input(self):
        """Accented input still matches non-accented option."""
        result = resolve_from_options("Balayagé", ["Balayage", "Corte"])
        assert result is not None
        assert result.value == "Balayage"


# =============================================================================
# resolve_time_slot()
# =============================================================================


_SLOTS = [
    {"time": "09:00", "stylist_name": "Ana"},
    {"time": "11:00", "stylist_name": "Victor"},
    {"time": "15:00", "stylist_name": "Marta"},
]


class TestResolveTimeSlot:
    """resolve_time_slot() extracts time expressions and matches slots."""

    def test_las_time(self):
        result = resolve_time_slot("a las 11", _SLOTS)
        assert result is not None
        assert result["time"] == "11:00"

    def test_bare_time_hhmm(self):
        result = resolve_time_slot("09:00", _SLOTS)
        assert result is not None
        assert result["time"] == "09:00"

    def test_media(self):
        slots = [{"time": "09:30", "stylist_name": "Ana"}]
        result = resolve_time_slot("a las 9 y media", slots)
        assert result is not None
        assert result["time"] == "09:30"

    def test_no_match(self):
        result = resolve_time_slot("a las 14", _SLOTS)
        assert result is None

    def test_ambiguous_two_slots_same_time(self):
        """Two slots at same time → None (ambiguous)."""
        slots = [
            {"time": "11:00", "stylist_name": "Ana"},
            {"time": "11:00", "stylist_name": "Victor"},
        ]
        result = resolve_time_slot("a las 11", slots)
        assert result is None

    def test_empty_input(self):
        assert resolve_time_slot("", _SLOTS) is None

    def test_empty_slots(self):
        assert resolve_time_slot("a las 11", []) is None

    def test_no_time_expression(self):
        result = resolve_time_slot("quiero reservar", _SLOTS)
        assert result is None


# =============================================================================
# resolve_ordinal()
# =============================================================================


class TestResolveOrdinal:
    """resolve_ordinal() returns 0-based index from ordinal expressions."""

    def test_digit_1(self):
        assert resolve_ordinal("1", 3) == 0

    def test_digit_2(self):
        assert resolve_ordinal("2", 3) == 1

    def test_digit_3(self):
        assert resolve_ordinal("3", 3) == 2

    def test_digit_out_of_range(self):
        assert resolve_ordinal("5", 3) is None

    def test_digit_zero(self):
        assert resolve_ordinal("0", 3) is None

    def test_primero(self):
        assert resolve_ordinal("primero", 3) == 0

    def test_la_primera(self):
        assert resolve_ordinal("la primera", 3) == 0

    def test_segunda(self):
        assert resolve_ordinal("la segunda", 3) == 1

    def test_tercero(self):
        assert resolve_ordinal("el tercero", 3) == 2

    def test_ultimo(self):
        result = resolve_ordinal("el último", 3)
        assert result == 2

    def test_out_of_range_ordinal(self):
        """cuarto (index 3) out of range for count=3."""
        result = resolve_ordinal("el cuarto", 3)
        assert result is None

    def test_empty_input(self):
        assert resolve_ordinal("", 3) is None

    def test_zero_count(self):
        assert resolve_ordinal("1", 0) is None

    def test_unrelated_text(self):
        assert resolve_ordinal("quiero el azul", 3) is None


# =============================================================================
# Tool fuzzy fallback — _resolve_service_by_name / _resolve_stylist_by_name
# =============================================================================


class TestToolFuzzyFallback:
    """WS-5: Tool-level fuzzy fallback when exact DB match returns None."""

    @pytest.mark.asyncio
    async def test_service_exact_match_no_fuzzy(self):
        """Exact match returns without loading all services."""
        mock_service = MagicMock()
        mock_service.name = "Balayage"

        with patch(
            "agent.tools.availability_tools.get_async_session",
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # First execute → exact match found
            mock_result = MagicMock()
            mock_result.scalar_one_or_none = MagicMock(return_value=mock_service)
            mock_session.execute = AsyncMock(return_value=mock_result)

            from agent.tools.availability_tools import _resolve_service_by_name

            result = await _resolve_service_by_name("Balayage")

        assert result is mock_service
        # Only one DB query (exact match path)
        assert mock_session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_service_fuzzy_match_on_typo(self):
        """'balayagee' → exact match fails → fuzzy fallback → returns Balayage service."""
        mock_service = MagicMock()
        mock_service.name = "Balayage"

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # First call: exact match → None
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                # Second call: all active services
                mock_result.scalars = MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[mock_service]))
                )
            return mock_result

        with patch(
            "agent.tools.availability_tools.get_async_session",
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = mock_execute

            from agent.tools.availability_tools import _resolve_service_by_name

            result = await _resolve_service_by_name("balayagee")

        assert result is mock_service

    @pytest.mark.asyncio
    async def test_service_below_threshold_returns_none(self):
        """'zzz' → exact match fails → fuzzy fallback finds nothing above 0.80."""
        mock_service = MagicMock()
        mock_service.name = "Balayage"

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                mock_result.scalars = MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[mock_service]))
                )
            return mock_result

        with patch(
            "agent.tools.availability_tools.get_async_session",
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = mock_execute

            from agent.tools.availability_tools import _resolve_service_by_name

            result = await _resolve_service_by_name("zzz")

        assert result is None

    @pytest.mark.asyncio
    async def test_stylist_fuzzy_match_on_typo(self):
        """'Victorr' → exact match fails → fuzzy fallback → returns Victor stylist."""
        mock_stylist = MagicMock()
        mock_stylist.name = "Victor"

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one_or_none = MagicMock(return_value=None)
            else:
                mock_result.scalars = MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[mock_stylist]))
                )
            return mock_result

        with patch(
            "agent.tools.availability_tools.get_async_session",
        ) as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = mock_execute

            from agent.tools.availability_tools import _resolve_stylist_by_name

            result = await _resolve_stylist_by_name("Victorr")

        assert result is mock_stylist
