"""Tests for booking structured-output Pydantic schemas — Phase 5.2."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent.booking.schemas import (
    AudienceResponse,
    ConfirmationResponse,
    DateResponse,
    NameResponse,
    NotesResponse,
    ServiceSelectionResponse,
    SlotResponse,
    StylistResponse,
)


class TestServiceSelectionResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            ServiceSelectionResponse(selected_service_ids=None, needs_clarification=False)

    def test_valid_minimal(self):
        r = ServiceSelectionResponse(message="ok", needs_clarification=False)
        assert r.message == "ok"
        assert r.selected_service_ids is None
        assert r.suggested_audience is None
        assert r.needs_clarification is False

    def test_with_ids(self):
        uid = uuid4()
        r = ServiceSelectionResponse(
            message="found", selected_service_ids=[uid], needs_clarification=False
        )
        assert r.selected_service_ids == [uid]

    def test_with_audience(self):
        r = ServiceSelectionResponse(
            message="found", needs_clarification=False, suggested_audience="adult_female"
        )
        assert r.suggested_audience == "adult_female"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ServiceSelectionResponse(message="x", needs_clarification=False, unknown_field="y")


class TestAudienceResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            AudienceResponse()

    def test_valid_with_audience(self):
        r = AudienceResponse(message="ok", inferred_audience="child_male")
        assert r.inferred_audience == "child_male"

    def test_valid_none_audience(self):
        r = AudienceResponse(message="¿para quién?")
        assert r.inferred_audience is None

    def test_invalid_audience_value(self):
        with pytest.raises(ValidationError):
            AudienceResponse(message="x", inferred_audience="MUJER")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            AudienceResponse(message="x", extra="y")


class TestStylistResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            StylistResponse()

    def test_valid_with_stylist(self):
        uid = uuid4()
        r = StylistResponse(message="ok", inferred_stylist_id=uid)
        assert r.inferred_stylist_id == uid

    def test_no_preference_flag(self):
        r = StylistResponse(message="sin preferencia", no_preference=True)
        assert r.no_preference is True

    def test_defaults(self):
        r = StylistResponse(message="¿con quién?")
        assert r.inferred_stylist_id is None
        assert r.no_preference is False

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            StylistResponse(message="x", bad="y")


class TestDateResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            DateResponse()

    def test_valid_with_date(self):
        d = date(2026, 5, 10)
        r = DateResponse(message="ok", inferred_date=d)
        assert r.inferred_date == d

    def test_none_date(self):
        r = DateResponse(message="¿qué día?")
        assert r.inferred_date is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            DateResponse(message="x", extra="y")


class TestSlotResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            SlotResponse()

    def test_valid_with_index(self):
        r = SlotResponse(message="slot 1", selected_slot_index=0)
        assert r.selected_slot_index == 0

    def test_none_index(self):
        r = SlotResponse(message="¿cuál turno?")
        assert r.selected_slot_index is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            SlotResponse(message="x", extra="y")


class TestNameResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            NameResponse()

    def test_valid(self):
        r = NameResponse(message="ok", first_name="Ana", first_surname="García")
        assert r.first_name == "Ana"
        assert r.first_surname == "García"

    def test_none_fields(self):
        r = NameResponse(message="¿tu nombre?")
        assert r.first_name is None
        assert r.first_surname is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            NameResponse(message="x", extra="y")


class TestNotesResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            NotesResponse()

    def test_with_notes(self):
        r = NotesResponse(message="anotado", notes="alergia al tinte", user_declined=False)
        assert r.notes == "alergia al tinte"
        assert r.user_declined is False

    def test_declined(self):
        r = NotesResponse(message="ok", user_declined=True)
        assert r.user_declined is True
        assert r.notes is None

    def test_defaults(self):
        r = NotesResponse(message="¿alguna nota?")
        assert r.notes is None
        assert r.user_declined is False

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            NotesResponse(message="x", extra="y")


class TestConfirmationResponse:
    def test_message_required(self):
        with pytest.raises(ValidationError):
            ConfirmationResponse()

    def test_confirmed_true(self):
        r = ConfirmationResponse(message="confirmado", confirmed=True)
        assert r.confirmed is True

    def test_confirmed_false(self):
        r = ConfirmationResponse(message="cancelado", confirmed=False)
        assert r.confirmed is False

    def test_confirmed_none(self):
        r = ConfirmationResponse(message="¿confirmás?")
        assert r.confirmed is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            ConfirmationResponse(message="x", extra="y")
