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
