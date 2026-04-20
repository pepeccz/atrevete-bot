"""Unit tests for `agent.booking.models._family_key`.

Pure-function tests for the dimension-based family key helper that replaces
the fragile `name.split()[0]` grouping in the audience ambiguity detector.

RED phase: `_family_key` does not yet exist in agent/booking/models.py.
"""

from __future__ import annotations


class TestFamilyKey:
    """_family_key(metadata_, audience) returns (dimension, 'principal') or None."""

    def test_principal_with_audience_returns_family_key(self):
        from agent.booking.models import _family_key

        metadata = {"service_type": "principal", "dimension": "cut", "parent_service_name": None}
        assert _family_key(metadata, "adult_female") == ("cut", "principal")

    def test_principal_without_audience_returns_none(self):
        from agent.booking.models import _family_key

        metadata = {"service_type": "principal", "dimension": "cut", "parent_service_name": None}
        assert _family_key(metadata, None) is None

    def test_variant_returns_none(self):
        from agent.booking.models import _family_key

        metadata = {
            "service_type": "variant",
            "dimension": "cut",
            "parent_service_name": "Corte Caballero",
        }
        assert _family_key(metadata, "adult_male") is None

    def test_missing_metadata_returns_none(self):
        from agent.booking.models import _family_key

        assert _family_key(None, "adult_female") is None
        assert _family_key({}, "adult_female") is None

    def test_missing_dimension_returns_none(self):
        from agent.booking.models import _family_key

        metadata = {"service_type": "principal", "parent_service_name": None}
        assert _family_key(metadata, "adult_female") is None

    def test_different_dimensions_produce_different_keys(self):
        from agent.booking.models import _family_key

        cut_meta = {"service_type": "principal", "dimension": "cut"}
        color_meta = {"service_type": "principal", "dimension": "color"}
        assert _family_key(cut_meta, "adult_female") != _family_key(color_meta, "adult_female")
