"""Pure assertion helpers for notification send-capture files.

All public functions are PURE — they accept plain dicts and raise ``AssertionError``
on failure.  No database, Redis, or network access.  No heavy imports at module top:
safe to import in lightweight unit-test environments that lack the full service stack.

Typical usage in a QA scenario script:
    from tests.e2e.harness.assert_notifications import (
        assert_send_attempt,
        assert_timestamp_stamped,
        assert_idempotent,
    )

    capture = json.loads(Path("notifications_capture.json").read_text())
    assert_send_attempt(capture, appointment_id=appt_id, handler="reminder_24h")
    assert_timestamp_stamped(capture, appointment_id=appt_id, handler="reminder_24h")

    second_capture = json.loads(Path("notifications_capture_2.json").read_text())
    assert_idempotent(capture, second_capture, appt_id)
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Timestamp column map — one source of truth for handler → DB column
# ---------------------------------------------------------------------------

_HANDLER_TIMESTAMP_COL: dict[str, str] = {
    "reminder_24h": "reminder_sent_at",
    "confirm_48h": "confirmation_sent_at",
    "final_warning": "final_warning_sent_at",
}


# ---------------------------------------------------------------------------
# Finders — return data with no side-effects
# ---------------------------------------------------------------------------


def find_send_attempts(
    capture: dict[str, Any],
    *,
    appointment_id: str | None = None,
    handler: str | None = None,
) -> list[dict[str, Any]]:
    """Return all send attempts matching the given filters (both optional).

    Args:
        capture: The full capture dict produced by ``fire_notifications.py``.
        appointment_id: When provided, keep only attempts with this appointment_id.
        handler: When provided, keep only attempts with this handler name.

    Returns:
        Filtered list (may be empty).
    """
    attempts: list[dict[str, Any]] = list(capture.get("send_attempts") or [])
    if appointment_id is not None:
        attempts = [a for a in attempts if a.get("appointment_id") == appointment_id]
    if handler is not None:
        attempts = [a for a in attempts if a.get("handler") == handler]
    return attempts


def find_db_state(
    capture: dict[str, Any],
    appointment_id: str,
) -> dict[str, Any] | None:
    """Return the DB-state entry for ``appointment_id``, or ``None``."""
    for row in capture.get("db_state") or []:
        if row.get("appointment_id") == appointment_id:
            return row
    return None


# ---------------------------------------------------------------------------
# Assertions — raise AssertionError with descriptive messages on failure
# ---------------------------------------------------------------------------


def assert_send_attempt(
    capture: dict[str, Any],
    *,
    appointment_id: str,
    handler: str,
) -> dict[str, Any]:
    """Assert that exactly one successful send attempt exists for the given pair.

    Args:
        capture: Capture dict from ``fire_notifications.py``.
        appointment_id: Expected appointment UUID string.
        handler: Expected handler name (``'reminder_24h'`` or ``'confirm_48h'``).

    Returns:
        The matched attempt dict, for further inspection by the caller.

    Raises:
        AssertionError: If zero or more-than-one matching attempts are found.
    """
    matches = find_send_attempts(capture, appointment_id=appointment_id, handler=handler)
    assert matches, (
        f"Expected a send attempt for appointment_id={appointment_id!r} "
        f"handler={handler!r} but found none.\n"
        f"All attempts: {capture.get('send_attempts', [])}"
    )
    assert len(matches) == 1, (
        f"Expected exactly 1 send attempt for appointment_id={appointment_id!r} "
        f"handler={handler!r} but found {len(matches)}: {matches}"
    )
    return matches[0]


def assert_timestamp_stamped(
    capture: dict[str, Any],
    *,
    appointment_id: str,
    handler: str,
) -> None:
    """Assert that the DB timestamp column was stamped after a successful send.

    Column mapping:
        reminder_24h   → ``reminder_sent_at``
        confirm_48h    → ``confirmation_sent_at``
        final_warning  → ``final_warning_sent_at``

    Args:
        capture: Capture dict from ``fire_notifications.py`` (must include ``db_state``).
        appointment_id: The appointment UUID to inspect.
        handler: Handler name that should have stamped the timestamp.

    Raises:
        ValueError: If ``handler`` is not a known handler name.
        AssertionError: If no DB state entry is found, or the timestamp column is ``None``.
    """
    col = _HANDLER_TIMESTAMP_COL.get(handler)
    if col is None:
        raise ValueError(
            f"Unknown handler {handler!r}. " f"Known handlers: {sorted(_HANDLER_TIMESTAMP_COL)}"
        )

    state = find_db_state(capture, appointment_id)
    assert state is not None, (
        f"No DB state entry found for appointment_id={appointment_id!r}.\n"
        f"Available IDs: {[r.get('appointment_id') for r in capture.get('db_state') or []]}"
    )

    val = state.get(col)
    assert val is not None, (
        f"Expected {col} to be stamped (non-null) for appointment_id={appointment_id!r} "
        f"(handler={handler!r}) but got: {val!r}.\n"
        f"Full DB state: {state}"
    )


def assert_no_failures(
    capture: dict[str, Any],
    *,
    appointment_id: str,
) -> None:
    """Assert that the DB state for ``appointment_id`` has no failure flags set.

    Checks ``reminder_failed`` and ``notification_failed`` are both ``False``.
    Both flags use ``state.get()`` so absent keys (e.g. captures from before Slice 3's
    ``_query_db_state`` extension) are treated as falsy — no assertion error.

    Raises:
        AssertionError: If any failure flag is truthy or the DB state entry is missing.
    """
    state = find_db_state(capture, appointment_id)
    assert state is not None, f"No DB state entry found for appointment_id={appointment_id!r}."
    for flag in ("reminder_failed", "notification_failed"):
        assert not state.get(flag), (
            f"Expected {flag}=False for appointment_id={appointment_id!r} "
            f"but got: {state.get(flag)!r}.\nFull DB state: {state}"
        )


def assert_idempotent(
    first_capture: dict[str, Any],
    second_capture: dict[str, Any],
    appointment_id: str,
) -> None:
    """Assert that a second fire produced NO new send attempts for ``appointment_id``.

    After a successful first fire the handler stamps the timestamp column.  The
    handler's ``query_fn`` excludes rows where that column is already set, so a
    second cycle MUST produce zero send attempts for the same appointment.

    Args:
        first_capture: Output of the first ``fire_notifications.py`` run.
        second_capture: Output of the second ``fire_notifications.py`` run.
        appointment_id: The appointment UUID to check for idempotency.

    Raises:
        AssertionError: If any send attempt for ``appointment_id`` appears in
            ``second_capture`` (idempotency violation).
    """
    # Verify the first capture actually sent something (guard against a vacuous pass).
    first_attempts = find_send_attempts(first_capture, appointment_id=appointment_id)
    assert first_attempts, (
        f"assert_idempotent: first capture has no send attempts for "
        f"appointment_id={appointment_id!r} — nothing to test idempotency against.\n"
        f"Check that seed_future_appointment placed the appointment in the correct window."
    )

    second_attempts = find_send_attempts(second_capture, appointment_id=appointment_id)
    assert not second_attempts, (
        f"Idempotency violation: second fire still produced {len(second_attempts)} "
        f"send attempt(s) for appointment_id={appointment_id!r}: {second_attempts}.\n"
        "The handler query_fn should exclude appointments where the timestamp is already set."
    )


def assert_auto_cancelled(
    capture: dict[str, Any],
    appointment_id: str,
) -> None:
    """Assert that the appointment was auto-cancelled with the canonical reason string.

    Checks the ``db_state`` entry directly — the ``auto_cancel`` handler performs a DB
    action rather than a Chatwoot send, so ``send_attempts`` carries no template data.

    Args:
        capture: Capture dict from ``fire_notifications.py`` (must include ``db_state``
            queried after the ``auto_cancel`` handler ran).
        appointment_id: The appointment UUID to inspect.

    Raises:
        AssertionError: If the DB state entry is missing, ``status`` is not
            ``'cancelled'``, ``cancellation_reason`` is not
            ``'auto_cancelled_no_confirmation'``, or ``cancelled_at`` is ``None``.
    """
    state = find_db_state(capture, appointment_id)
    assert state is not None, (
        f"No DB state entry found for appointment_id={appointment_id!r}.\n"
        f"Available IDs: {[r.get('appointment_id') for r in capture.get('db_state') or []]}"
    )
    assert state.get("status") == "cancelled", (
        f"Expected status='cancelled' for appointment_id={appointment_id!r} "
        f"but got: {state.get('status')!r}.\nFull DB state: {state}"
    )
    assert state.get("cancellation_reason") == "auto_cancelled_no_confirmation", (
        f"Expected cancellation_reason='auto_cancelled_no_confirmation' "
        f"for appointment_id={appointment_id!r} "
        f"but got: {state.get('cancellation_reason')!r}.\nFull DB state: {state}"
    )
    assert state.get("cancelled_at") is not None, (
        f"Expected cancelled_at to be set (non-null) for appointment_id={appointment_id!r} "
        f"but got: {state.get('cancelled_at')!r}.\nFull DB state: {state}"
    )
