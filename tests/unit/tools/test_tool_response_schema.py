"""RED test — T1: ToolResponse must have collected + missing fields.

These tests will FAIL on master (fields absent) and pass after GREEN impl.
Refs: R1
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.tools.schemas import ToolResponse


class TestToolResponseFields:
    def test_has_collected_field(self):
        r = ToolResponse(status="ok")
        assert hasattr(r, "collected")
        assert r.collected == {}

    def test_has_missing_field(self):
        r = ToolResponse(status="ok")
        assert hasattr(r, "missing")
        assert r.missing == []

    def test_collected_accepts_dict(self):
        r = ToolResponse(status="partial", collected={"services": ["corte dama"]})
        assert r.collected == {"services": ["corte dama"]}

    def test_missing_accepts_list_of_str(self):
        r = ToolResponse(status="partial", missing=["stylist", "date"])
        assert r.missing == ["stylist", "date"]


class TestToolResponseConstraints:
    def test_extra_forbid_enforced(self):
        with pytest.raises(ValidationError):
            ToolResponse(status="ok", unknown_field="x")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ToolResponse(status="complete")

    def test_valid_statuses(self):
        for s in ("ok", "partial", "rejected"):
            r = ToolResponse(status=s)
            assert r.status == s


class TestSuggestionResponseContract:
    """Verifies that service_suggestion_required is registered in the payload contract.

    GREEN as of PR 1 (next_steps.py ships the value + contract entry); emission
    of the next_step is PR 2.
    Refs: tasks 1.2, design ADR-1.
    """

    def test_service_suggestion_required_in_vocab(self):
        """service_suggestion_required must be in the NextStep Literal."""
        from agent.tools.next_steps import NextStep

        assert "service_suggestion_required" in NextStep.__args__

    def test_service_suggestion_required_in_payload_contract(self):
        """service_suggestion_required must be registered in NEXT_STEP_PAYLOAD_CONTRACT."""
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        assert "service_suggestion_required" in NEXT_STEP_PAYLOAD_CONTRACT

    def test_suggestion_payload_contract_has_unknown_terms_key(self):
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        keys = NEXT_STEP_PAYLOAD_CONTRACT.get("service_suggestion_required", ())
        assert "unknown_terms" in keys

    def test_suggestion_payload_contract_has_candidates_key(self):
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        keys = NEXT_STEP_PAYLOAD_CONTRACT.get("service_suggestion_required", ())
        assert "candidates" in keys

    def test_suggestion_response_json_roundtrip(self):
        """ToolResponse with suggestion payload survives JSON serialization."""
        from agent.tools.schemas import ToolResponse

        r = ToolResponse(
            status="rejected",
            next_step="service_suggestion_required",
            payload={
                "unknown_terms": ["pelado"],
                "candidates": ["Corte de Hombre", "Corte de Niño"],
            },
        )
        r2 = ToolResponse.model_validate_json(r.model_dump_json())
        assert r2.next_step == "service_suggestion_required"
        assert r2.payload["unknown_terms"] == ["pelado"]
        assert "Corte de Hombre" in r2.payload["candidates"]


class TestToolResponseRoundTrip:
    def test_json_roundtrip_full_slots(self):
        r = ToolResponse(
            status="ok",
            collected={"services": ["corte dama"], "stylist_id": "abc"},
            missing=[],
            next_step="booking_ready",
            payload={},
            errors=[],
        )
        r2 = ToolResponse.model_validate_json(r.model_dump_json())
        assert r == r2

    def test_json_roundtrip_partial(self):
        r = ToolResponse(
            status="partial",
            collected={"services": ["peinado"]},
            missing=["stylist", "date"],
            next_step="stylist_required",
        )
        r2 = ToolResponse.model_validate_json(r.model_dump_json())
        assert r == r2

    def test_json_roundtrip_rejected(self):
        r = ToolResponse(
            status="rejected",
            errors=["No reconozco el servicio: peeling"],
            next_step="service_required",
        )
        r2 = ToolResponse.model_validate_json(r.model_dump_json())
        assert r == r2
