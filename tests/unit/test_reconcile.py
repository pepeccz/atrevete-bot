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
    "mismatches": [
        "audience='adult_male' not matched by any booked service (got: ['adult_female'])"
    ],
    "booked_summary": [
        {"name": "Corte de Mujer", "audience": "adult_female", "service_type": "principal"}
    ],
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


# ---------------------------------------------------------------------------
# Consent fixtures
# ---------------------------------------------------------------------------

_CONSENT_INFO_OK = {
    "policy_accepted_at": "2026-06-17T10:00:00+00:00",
    "policy_version": "1.0",
    "consent_rows": 1,
}
_CONSENT_INFO_MISSING = {
    "policy_accepted_at": None,
    "policy_version": None,
    "consent_rows": 0,
}

_CONSENT_EXPECTED_OK = {"expected": True, "consent_ok": True, "consent_info": _CONSENT_INFO_OK}
_CONSENT_EXPECTED_FAIL = {
    "expected": True,
    "consent_ok": False,
    "consent_info": _CONSENT_INFO_MISSING,
}
_CONSENT_NOT_EXPECTED = {
    "expected": False,
    "consent_ok": False,
    "consent_info": _CONSENT_INFO_MISSING,
}


# ---------------------------------------------------------------------------
# (a) consent expected + consent_ok True → does not fail l4_pass
# ---------------------------------------------------------------------------
def test_consent_expected_and_ok_passes() -> None:
    result = compute_l4_verdict(_NO_HALLUCINATION, service_match=None, consent=_CONSENT_EXPECTED_OK)
    assert result["l4_pass"] is True
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# (b) consent expected + consent_ok False → l4_pass False with consent finding
# ---------------------------------------------------------------------------
def test_consent_expected_but_missing_fails() -> None:
    result = compute_l4_verdict(
        _NO_HALLUCINATION, service_match=None, consent=_CONSENT_EXPECTED_FAIL
    )
    assert result["l4_pass"] is False
    assert len(result["findings"]) == 1
    assert "consent not persisted" in result["findings"][0]
    assert "policy_accepted_at=None" in result["findings"][0]
    assert "expected a stored consent" in result["findings"][0]


# ---------------------------------------------------------------------------
# (c) consent=None (not asserted) → backward compatible, does not affect verdict
# ---------------------------------------------------------------------------
def test_consent_none_is_ignored() -> None:
    result = compute_l4_verdict(_NO_HALLUCINATION, service_match=None, consent=None)
    assert result["l4_pass"] is True
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# (d) consent expected=False → ignored even when consent_ok is False
# ---------------------------------------------------------------------------
def test_consent_not_expected_is_ignored() -> None:
    result = compute_l4_verdict(
        _NO_HALLUCINATION, service_match=None, consent=_CONSENT_NOT_EXPECTED
    )
    assert result["l4_pass"] is True
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# (e) combined: no hallucination + service match ok + consent expected + ok → passes
# ---------------------------------------------------------------------------
def test_all_pass_with_consent() -> None:
    result = compute_l4_verdict(
        _NO_HALLUCINATION,
        service_match=_SERVICE_MATCH_OK,
        consent=_CONSENT_EXPECTED_OK,
    )
    assert result["l4_pass"] is True
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# (f) backward compat: positional call (hallucination, service_match) still works
# ---------------------------------------------------------------------------
def test_backward_compat_two_args() -> None:
    result = compute_l4_verdict(_NO_HALLUCINATION, _SERVICE_MATCH_OK)
    assert result["l4_pass"] is True
    assert result["findings"] == []
