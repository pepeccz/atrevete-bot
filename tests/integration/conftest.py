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
    """Canonicalize JSON request bodies so cassettes are key-order agnostic."""
    if request.body and request.headers.get("Content-Type", "").startswith("application/json"):
        try:
            body = json.loads(request.body)
            request.body = json.dumps(body, sort_keys=True).encode()
        except (json.JSONDecodeError, TypeError):
            pass
    return request


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
        "record_mode": "none",
    }
