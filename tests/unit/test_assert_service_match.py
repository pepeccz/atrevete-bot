"""Unit tests for check_service_match (pure, no I/O, no DB).

Covers:
- (a) name_contains match and mismatch
- (b) audience match and mismatch
- (c) service_type match and mismatch
- (d) forbidden_audience triggers mismatch when present
- (e) only present keys are asserted (empty expected → match True)
- (f) defensive on None/missing fields in booked_services
"""

from __future__ import annotations

import pytest

from tests.e2e.harness.assert_service_match import check_service_match


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CORTE_DAMA = {"name": "Corte de Mujer", "audience": "adult_female", "service_type": "principal"}
CORTE_HOMBRE = {"name": "Corte de Hombre", "audience": "adult_male", "service_type": "principal"}
TINTE = {"name": "Tinte", "audience": "adult_female", "service_type": "principal"}
ADDON = {"name": "Tinte Extra", "audience": None, "service_type": "addon"}


# ---------------------------------------------------------------------------
# (a) name_contains
# ---------------------------------------------------------------------------


def test_name_contains_match() -> None:
    """At least one booked service name contains the needle (case-insensitive)."""
    result = check_service_match([CORTE_DAMA], {"name_contains": "corte"})
    assert result["match"] is True
    assert result["mismatches"] == []


def test_name_contains_case_insensitive() -> None:
    """name_contains match is case-insensitive."""
    result = check_service_match([CORTE_DAMA], {"name_contains": "CORTE DE MUJER"})
    assert result["match"] is True


def test_name_contains_mismatch() -> None:
    """Fails when no service name contains the needle."""
    result = check_service_match([TINTE], {"name_contains": "corte"})
    assert result["match"] is False
    assert len(result["mismatches"]) == 1
    assert "corte" in result["mismatches"][0]
    assert "Tinte" in result["mismatches"][0]


def test_name_contains_multi_service_any_match() -> None:
    """Passes when at least one of several booked services matches."""
    result = check_service_match([TINTE, CORTE_DAMA], {"name_contains": "corte"})
    assert result["match"] is True


# ---------------------------------------------------------------------------
# (b) audience
# ---------------------------------------------------------------------------


def test_audience_match() -> None:
    """Passes when at least one service has the expected audience."""
    result = check_service_match([CORTE_DAMA], {"audience": "adult_female"})
    assert result["match"] is True


def test_audience_mismatch() -> None:
    """Fails when no service has the expected audience."""
    result = check_service_match([CORTE_HOMBRE], {"audience": "adult_female"})
    assert result["match"] is False
    assert any("adult_female" in m for m in result["mismatches"])


def test_audience_none_does_not_match_string() -> None:
    """An addon with audience=None does not satisfy an audience assertion."""
    result = check_service_match([ADDON], {"audience": "adult_female"})
    assert result["match"] is False


def test_audience_multi_any_match() -> None:
    """Passes when at least one service in a mixed list has the right audience."""
    result = check_service_match([CORTE_HOMBRE, CORTE_DAMA], {"audience": "adult_female"})
    assert result["match"] is True


# ---------------------------------------------------------------------------
# (c) service_type
# ---------------------------------------------------------------------------


def test_service_type_match() -> None:
    """Passes when at least one service has the expected service_type."""
    result = check_service_match([CORTE_DAMA], {"service_type": "principal"})
    assert result["match"] is True


def test_service_type_mismatch() -> None:
    """Fails when no service has the expected service_type."""
    result = check_service_match([ADDON], {"service_type": "principal"})
    assert result["match"] is False
    assert any("principal" in m for m in result["mismatches"])


def test_service_type_addon_match() -> None:
    """Passes when the expected type is 'addon' and a matching service exists."""
    result = check_service_match([ADDON], {"service_type": "addon"})
    assert result["match"] is True


# ---------------------------------------------------------------------------
# (d) forbidden_audience
# ---------------------------------------------------------------------------


def test_forbidden_audience_absent_passes() -> None:
    """Passes when no booked service has the forbidden audience."""
    result = check_service_match([CORTE_DAMA], {"forbidden_audience": "adult_male"})
    assert result["match"] is True


def test_forbidden_audience_present_fails() -> None:
    """Fails when at least one booked service carries the forbidden audience."""
    result = check_service_match([CORTE_HOMBRE], {"forbidden_audience": "adult_male"})
    assert result["match"] is False
    assert any("forbidden_audience" in m for m in result["mismatches"])
    assert any("Corte de Hombre" in m for m in result["mismatches"])


def test_forbidden_audience_none_not_flagged() -> None:
    """audience=None on a booked service does not trigger the forbidden guard."""
    result = check_service_match([ADDON], {"forbidden_audience": "adult_male"})
    assert result["match"] is True


def test_forbidden_audience_mixed_list_detects_violator() -> None:
    """Fails when one service in a mixed list carries the forbidden audience."""
    result = check_service_match(
        [CORTE_DAMA, CORTE_HOMBRE], {"forbidden_audience": "adult_male"}
    )
    assert result["match"] is False


# ---------------------------------------------------------------------------
# (e) only present keys are asserted
# ---------------------------------------------------------------------------


def test_empty_expected_always_passes() -> None:
    """Vacuous truth: empty expected dict passes regardless of services."""
    result = check_service_match([CORTE_DAMA, TINTE, ADDON], {})
    assert result["match"] is True
    assert result["mismatches"] == []


def test_absent_key_not_checked() -> None:
    """Keys absent from expected are never checked, even if values differ."""
    # Only checking service_type=principal; audience and name_contains are absent
    result = check_service_match([CORTE_DAMA], {"service_type": "principal"})
    assert result["match"] is True
    # Confirm we didn't accidentally add audience/name mismatch
    assert result["mismatches"] == []


def test_multiple_keys_all_pass() -> None:
    """All present keys must pass for overall match to be True."""
    result = check_service_match(
        [CORTE_DAMA],
        {
            "name_contains": "corte",
            "audience": "adult_female",
            "service_type": "principal",
            "forbidden_audience": "adult_male",
        },
    )
    assert result["match"] is True
    assert result["mismatches"] == []


def test_multiple_keys_partial_fail() -> None:
    """Multiple mismatches are all collected, match is False."""
    # ADDON has no audience and service_type=addon — both audience and service_type will fail
    result = check_service_match(
        [ADDON],
        {"audience": "adult_female", "service_type": "principal"},
    )
    assert result["match"] is False
    assert len(result["mismatches"]) == 2


# ---------------------------------------------------------------------------
# (f) defensive on None / missing fields
# ---------------------------------------------------------------------------


def test_none_name_does_not_crash() -> None:
    """A service with name=None does not raise; name_contains simply won't match it."""
    result = check_service_match([{"name": None, "audience": None, "service_type": None}], {})
    assert result["match"] is True  # empty expected → vacuous pass


def test_missing_fields_uses_none() -> None:
    """Entries missing keys are treated as None for each field."""
    result = check_service_match([{}], {"audience": "adult_female"})
    assert result["match"] is False  # None != "adult_female"


def test_non_dict_entries_skipped() -> None:
    """Non-dict items in booked_services are skipped without raising."""
    result = check_service_match(["not a dict", None, 42], {"service_type": "principal"})  # type: ignore[list-item]
    # All non-dicts stripped → effectively empty → no services to match → fails
    assert result["match"] is False


def test_empty_booked_with_nonempty_expected_fails() -> None:
    """Empty booked list with any expectation returns match=False with a clear message."""
    result = check_service_match([], {"name_contains": "corte"})
    assert result["match"] is False
    assert "no booked services" in result["mismatches"][0]


def test_booked_summary_always_returned() -> None:
    """booked_summary is always present in the result dict."""
    result = check_service_match([CORTE_DAMA], {"service_type": "principal"})
    assert "booked_summary" in result
    assert len(result["booked_summary"]) == 1
    assert result["booked_summary"][0]["name"] == "Corte de Mujer"


def test_name_contains_empty_needle_passes() -> None:
    """Empty string needle is treated as 'no constraint' and always passes."""
    result = check_service_match([TINTE], {"name_contains": ""})
    assert result["match"] is True
