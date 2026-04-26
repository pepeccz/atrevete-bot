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

    b1 = _canon(r1.body)
    b2 = _canon(r2.body)
    assert b1 == b2, "JSON body mismatch (canonical compare)"


# ---------------------------------------------------------------------------
# VCR configuration fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """Shared VCR configuration for all integration tests."""
    return {
        "match_on": ["method", "scheme", "host", "path", "query", "json_body"],
        "filter_headers": [
            ("Authorization", "REDACTED"),
            ("X-Api-Key", "REDACTED"),
            ("openai-organization", "REDACTED"),
        ],
        "before_record_request": _normalize_body,
        "decode_compressed_response": True,
        "record_mode": "none",
    }


def pytest_recording_configure(config: Any, vcr: Any) -> None:
    """Register the custom ``json_body`` matcher with the VCR instance.

    pytest-recording calls this hook once when the VCR object is created.
    """
    vcr.register_matcher("json_body", _json_body_matcher)
