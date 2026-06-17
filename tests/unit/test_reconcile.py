"""Unit tests for the L4 reconcile verdict helper (pure, no DB, no I/O).

Tests cover compute_l4_verdict() which is factored out of _cmd_reconcile so it
can be exercised without async context or database access.
"""

from __future__ import annotations

from tests.e2e.harness.qa_turn_helper import compute_l4_verdict


# ---------------------------------------------------------------------------
# Fixtures — representative inputs
# ---------------------------------------------------------------------------

_NO_HALLUCINATION = {"hallucinated_confirmation": False, "matched_phrase": None}
_HALLUCINATION = {
    "hallucinated_confirmation": True,
    "matched_phrase": "te he confirmado la cita",
}
_SERVICE_MATCH_OK = {"match": True, "mismatches": [], "booked_summary": []}
_SERVICE_MATCH_FAIL = {
    "match": False,
    "mismatches": ["audience='adult_male' not matched by any booked service (got: ['adult_female'])"],
    "booked_summary": [{"name": "Corte de Mujer", "audience": "adult_female", "service_type": "principal"}],
}


# ---------------------------------------------------------------------------
# (a) no hallucination + no service spec → l4_pass True, no findings
# ---------------------------------------------------------------------------
def test_no_hallucination_no_spec_passes() -> None:
    result = compute_l4_verdict(_NO_HALLUCINATION, service_match=None)
    assert result["l4_pass"] is True
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# (b) hallucination True → l4_pass False, finding mentions matched phrase
# ---------------------------------------------------------------------------
def test_hallucination_fails_with_finding() -> None:
    result = compute_l4_verdict(_HALLUCINATION, service_match=None)
    assert result["l4_pass"] is False
    assert len(result["findings"]) == 1
    assert "hallucinated confirmation" in result["findings"][0]
    assert "te he confirmado la cita" in result["findings"][0]


# ---------------------------------------------------------------------------
# (c) service_match match=False → l4_pass False, finding from mismatches
# ---------------------------------------------------------------------------
def test_service_mismatch_fails_with_finding() -> None:
    result = compute_l4_verdict(_NO_HALLUCINATION, service_match=_SERVICE_MATCH_FAIL)
    assert result["l4_pass"] is False
    assert len(result["findings"]) == 1
    assert "service mismatch" in result["findings"][0]
    assert "adult_male" in result["findings"][0]


# ---------------------------------------------------------------------------
# (d) both fail → two findings present
# ---------------------------------------------------------------------------
def test_both_fail_two_findings() -> None:
    result = compute_l4_verdict(_HALLUCINATION, service_match=_SERVICE_MATCH_FAIL)
    assert result["l4_pass"] is False
    assert len(result["findings"]) == 2
    findings_text = " ".join(result["findings"])
    assert "hallucinated confirmation" in findings_text
    assert "service mismatch" in findings_text


# ---------------------------------------------------------------------------
# (e) service_match=None is not asserted, so passing hallucination → l4_pass True
# ---------------------------------------------------------------------------
def test_service_match_none_is_ignored() -> None:
    """When service_match is None (not asserted), it does not contribute to verdict."""
    result = compute_l4_verdict(_NO_HALLUCINATION, service_match=None)
    assert result["l4_pass"] is True


# ---------------------------------------------------------------------------
# Extra: service_match=True with no hallucination → passes
# ---------------------------------------------------------------------------
def test_all_pass() -> None:
    result = compute_l4_verdict(_NO_HALLUCINATION, service_match=_SERVICE_MATCH_OK)
    assert result["l4_pass"] is True
    assert result["findings"] == []
