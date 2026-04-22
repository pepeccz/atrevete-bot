"""Shared fixtures for contract tests."""

from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture
def availability_booking_state():
    """State fixture for fetch_availability_node — uses booking.date (pre-fix key name)."""
    return {
        "booking": {
            "step": "date",
            "service_ids": [str(uuid4())],
            "audience": "adult_female",
            "stylist_id": str(uuid4()),
            "date": "2026-05-01",
            "offered_slots": None,
            "selected_slot": None,
            "customer_full_name": "Ana García",
        },
        "messages": [],
        "conversation_id": "conv-contract-1",
        "customer_phone": "+34600000001",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "",
    }


@pytest.fixture
def book_booking_state():
    """State fixture for execute_book_node — includes a valid selected_slot with start_iso."""
    stylist_id = str(uuid4())
    return {
        "booking": {
            "step": "confirm",
            "service_ids": [str(uuid4())],
            "audience": "adult_female",
            "stylist_id": stylist_id,
            "date": "2026-05-01",
            "offered_slots": None,
            "selected_slot": {
                "start_iso": "2026-05-01T10:00:00-03:00",
                "end_iso": "2026-05-01T10:30:00-03:00",
                "stylist_id": stylist_id,
            },
            "customer_full_name": "Ana García",
            "notes": None,
        },
        "messages": [],
        "conversation_id": "conv-contract-2",
        "customer_phone": "+34600000002",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "",
    }


@pytest.fixture
def book_booking_state_no_stylist(book_booking_state):
    """Same as book_booking_state but stylist_id is None — triggers abort guard."""
    state = dict(book_booking_state)
    booking = dict(state["booking"])
    booking["stylist_id"] = None
    state["booking"] = booking
    return state
