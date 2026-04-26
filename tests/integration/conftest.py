"""Integration test configuration — VCR cassette fixtures.

pytest-recording wraps vcrpy. The vcr_config fixture is picked up automatically
by any test decorated with @pytest.mark.vcr.

Record mode:
- CI/default: "none"  — playback only; fails loudly if cassette is missing.
- Local re-record: run with --record-mode=rewrite (see scripts/refresh_booking_cassettes.sh).
"""
from __future__ import annotations

import json
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Body canonicalization — ensures JSON bodies match even if key order varies
# ---------------------------------------------------------------------------


def _normalize_body(request: Any) -> Any:
    """Canonicalize JSON request bodies so cassettes are key-order agnostic.

    Applied via ``before_record_request`` (during recording) so cassettes are
    written in canonical sorted-keys form. Playback uses the ``json_body``
    matcher below to canonicalize the live request before comparing.
    """
    if request.body and request.headers.get("Content-Type", "").startswith("application/json"):
        try:
            body = json.loads(request.body)
            request.body = json.dumps(body, sort_keys=True).encode()
        except (json.JSONDecodeError, TypeError):
            pass
    return request


def _json_body_matcher(r1: Any, r2: Any) -> None:
    """Custom matcher: compare JSON request bodies in canonical (sorted-keys) form.

    Why we need this: ``before_record_request`` only normalizes on RECORD. During
    playback the raw httpx request body is compared as-is to the cassette body.
    httpx/openai may emit dict keys in non-deterministic order across runs, so a
    byte comparison can fail even when the semantic content matches.

    vcrpy contract: silent return = match, raise AssertionError = mismatch.
    """

    def _canon(body: Any) -> bytes:
        if not body:
            return b""
        if isinstance(body, bytes):
            try:
                return json.dumps(json.loads(body), sort_keys=True).encode()
            except (json.JSONDecodeError, TypeError):
                return body
        if isinstance(body, str):
            try:
                return json.dumps(json.loads(body), sort_keys=True).encode()
            except (json.JSONDecodeError, TypeError):
                return body.encode()
        return str(body).encode()

    # Use vcrpy's read_body which handles iterator/file-like bodies safely.
    from vcr.matchers import read_body  # local import: vcr is a runtime dep of pytest-recording
    b1 = _canon(read_body(r1))
    b2 = _canon(read_body(r2))
    if b1 != b2:
        # Debug aid: dump live + cassette canonical bodies for the first mismatch
        try:
            import os
            dbg_dir = "/tmp/vcr-debug"
            os.makedirs(dbg_dir, exist_ok=True)
            n = len(os.listdir(dbg_dir))
            with open(f"{dbg_dir}/live_{n:03d}.json", "wb") as f:
                f.write(b1)
            with open(f"{dbg_dir}/cass_{n:03d}.json", "wb") as f:
                f.write(b2)
        except Exception:
            pass
    assert b1 == b2, "JSON body mismatch (canonical compare)"


# ---------------------------------------------------------------------------
# VCR configuration fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """Shared VCR configuration for all integration tests."""
    return {
        "match_on": ["method", "scheme", "host", "path", "query", "body"],
        "filter_headers": [
            ("Authorization", "REDACTED"),
            ("X-Api-Key", "REDACTED"),
            ("openai-organization", "REDACTED"),
        ],
        "before_record_request": _normalize_body,
        "decode_compressed_response": True,
        # record_mode intentionally omitted: pytest-recording derives it from
        # the --record-mode CLI flag (default "none" for safe CI playback).
    }


def pytest_recording_configure(config: Any, vcr: Any) -> None:
    """Register the custom ``json_body`` matcher with the VCR instance.

    pytest-recording calls this hook once when the VCR object is created.
    """
    vcr.register_matcher("json_body", _json_body_matcher)


# ---------------------------------------------------------------------------
# Test-data isolation — wipe stale appointments for the S5 test phone
# ---------------------------------------------------------------------------
#
# S5 (test_s5_confirmation_gate) records a real book() call against +34600000001
# which writes a row to `appointments`. Subsequent playbacks then see that row
# in DB state and check_availability returns DIFFERENT slots than at record
# time. The cassette becomes invalid because tool-result content (slots list)
# fed back into the LLM differs byte-for-byte.
#
# Fix: before each S5 invocation (record OR playback), delete every appointment
# attached to phone +34600000001. This guarantees the salon calendar is empty
# for that phone, matching the state captured during the original recording.


@pytest.fixture(autouse=True)
async def _wipe_test_phone_appointments(request: pytest.FixtureRequest) -> None:
    """Delete appointments for phone +34600000001 before each integration test.

    Only active for tests in ``tests/integration/test_booking_real_llm.py``.
    Uses an async SQLAlchemy session so it cooperates with pytest-asyncio.
    """
    if "test_booking_real_llm" not in str(request.fspath):
        return
    try:
        from sqlalchemy import text
        from database.connection import get_async_session

        async with get_async_session() as session:
            await session.execute(
                text(
                    "DELETE FROM appointments WHERE customer_id IN ("
                    "SELECT id FROM customers WHERE phone LIKE '%600000001')"
                )
            )
            await session.commit()
    except Exception:
        # Best-effort: do not block tests if DB is unreachable.
        pass
