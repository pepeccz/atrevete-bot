"""Unit tests for the unbacked-confirmation regression guard (F1).

Pure tests — no DB, no services. Cover the three core branches of
detect_unbacked_confirmation plus a couple of conservative-regex guards.
"""

from __future__ import annotations

from tests.e2e.harness.assert_claim_backend import detect_unbacked_confirmation


def test_confirmation_phrase_without_appointment_is_flagged() -> None:
    """(a) confirmation phrase + appointment_exists False → flagged."""
    messages = ["Perfecto, te he confirmado la cita para el jueves."]
    result = detect_unbacked_confirmation(messages, appointment_exists=False)
    assert result["hallucinated_confirmation"] is True
    assert result["matched_phrase"] is not None


def test_confirmation_phrase_with_appointment_is_not_flagged() -> None:
    """(b) confirmation phrase + appointment_exists True → NOT flagged."""
    messages = ["Perfecto, te he confirmado la cita para el jueves."]
    result = detect_unbacked_confirmation(messages, appointment_exists=True)
    assert result["hallucinated_confirmation"] is False
    assert result["matched_phrase"] is None


def test_no_confirmation_phrase_is_not_flagged() -> None:
    """(c) no confirmation phrase → NOT flagged even without an appointment."""
    messages = ["¿Para qué servicio quieres la cita?", "Tengo huecos el jueves."]
    result = detect_unbacked_confirmation(messages, appointment_exists=False)
    assert result["hallucinated_confirmation"] is False
    assert result["matched_phrase"] is None


def test_question_phrasing_is_not_treated_as_confirmation() -> None:
    """Conservative regex: an interrogative '¿Te lo confirmo?' is NOT a confirmation."""
    messages = ["Te lo dejo el jueves a las 10:00 con Ana. ¿Te lo confirmo?"]
    result = detect_unbacked_confirmation(messages, appointment_exists=False)
    assert result["hallucinated_confirmation"] is False


def test_listo_with_cita_is_flagged_as_booking() -> None:
    """'Listo, ... cita' matches the booking phrasing (the ¡Listo!...cit pattern).

    NOTE: this helper is BOOKING-scoped. 'Listo' near 'cita' reads as a fresh-booking
    confirmation, so it is still flagged when no appointment exists.
    """
    messages = ["Listo, tu cita queda lista."]
    result = detect_unbacked_confirmation(messages, appointment_exists=False)
    assert result["hallucinated_confirmation"] is True
    assert result["matched_phrase"] is not None


def test_bare_cancel_message_is_not_flagged_booking_scope() -> None:
    """BLOCKER-1: cancel/reschedule phrasing is NOT covered by this booking-scoped guard.

    The real manage_appointments cancel message ('Tu cita ha sido cancelada.') must NOT
    be flagged here — cancellation success cannot be verified (manage_appointments
    returns a plain string), so gating it would false-positive on legitimate cancels.
    """
    messages = ["Tu cita ha sido cancelada."]
    result = detect_unbacked_confirmation(messages, appointment_exists=False)
    assert result["hallucinated_confirmation"] is False
    assert result["matched_phrase"] is None


def test_reserva_confirmada_variant_is_flagged() -> None:
    """'reserva confirmada' phrasing is matched."""
    messages = ["¡Reserva confirmada! Te esperamos."]
    result = detect_unbacked_confirmation(messages, appointment_exists=False)
    assert result["hallucinated_confirmation"] is True


def test_empty_and_malformed_messages_are_tolerated() -> None:
    """Empty list and non-string entries do not raise and are not flagged."""
    result = detect_unbacked_confirmation([], appointment_exists=False)
    assert result["hallucinated_confirmation"] is False
    result2 = detect_unbacked_confirmation(["", "   "], appointment_exists=False)
    assert result2["hallucinated_confirmation"] is False
