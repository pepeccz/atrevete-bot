"""Tests for AudienceTag — Task 1.1 (booking-prompts-audit-fix).

Spec: AudienceTag MUST contain exactly 6 values including "baby".
      Assignment of "infant" MUST raise ValidationError.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from agent.state import AudienceTag


class _TagHolder(BaseModel):
    tag: AudienceTag


def test_baby_is_valid_audience_tag():
    """'baby' must be accepted as a valid AudienceTag value."""
    holder = _TagHolder(tag="baby")
    assert holder.tag == "baby"


def test_infant_is_invalid_audience_tag():
    """'infant' must NOT be a valid AudienceTag — Pydantic must raise ValidationError."""
    with pytest.raises(ValidationError):
        _TagHolder(tag="infant")


def test_audience_tag_has_exactly_6_values():
    """AudienceTag Literal must have exactly 6 members."""
    values = get_args(AudienceTag)
    assert len(values) == 6, f"Expected 6 values, got {len(values)}: {values}"


def test_all_expected_audience_tag_values_present():
    """All 6 canonical values must be present in AudienceTag."""
    values = set(get_args(AudienceTag))
    expected = {"adult_female", "adult_male", "child_female", "child_male", "unisex", "baby"}
    assert values == expected
