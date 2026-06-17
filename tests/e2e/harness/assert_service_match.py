"""Pure deterministic service-type / audience validation for QA scenarios.

Checks that the services actually booked match an expected spec dict.
No I/O, no DB — the caller is responsible for resolving booked_services
from the database and passing them in.

Usage:
    booked = [
        {"name": "Corte de Mujer", "audience": "adult_female", "service_type": "principal"},
    ]
    expected = {"name_contains": "corte", "audience": "adult_female", "service_type": "principal"}
    result = check_service_match(booked, expected)
    # result["match"] -> True | False
    # result["mismatches"] -> list[str] of human-readable failure reasons
    # result["booked_summary"] -> list of dicts with resolved service fields
"""

from __future__ import annotations

from typing import Any


def check_service_match(
    booked_services: list[dict[str, Any]],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically validate booked services against an expected spec.

    Args:
        booked_services: List of dicts, one per booked service.
            Expected keys (all optional/nullable):
                - name (str | None): Service name.
                - audience (str | None): e.g. "adult_female", "adult_male", or None.
                - service_type (str | None): "principal" | "variant" | "addon" | None.

        expected: Spec dict controlling which assertions to run. All keys are optional.
            - name_contains (str): Case-insensitive substring. At least one booked
              service's name must contain this string.
            - audience (str): Exact match. At least one booked service must have
              this audience value.
            - service_type (str): Exact match. At least one booked service must have
              this service_type value.
            - forbidden_audience (str): NO booked service may have this audience value.

    Returns:
        {
            "match": bool,          # True iff all present keys pass
            "mismatches": list[str],# Human-readable failure reasons (empty when match=True)
            "booked_summary": list, # Echo of booked_services (normalized, for logging)
        }

    Behavior:
        - Only keys present in `expected` are asserted. Absent keys are not checked.
        - Defensive against None/missing fields in booked_services entries.
        - Empty expected dict always returns match=True (vacuous truth).
        - Empty booked_services with any non-empty expected spec returns match=False.
    """
    mismatches: list[str] = []

    # Normalize booked_services so callers with partial dicts are handled gracefully.
    normalized: list[dict[str, Any]] = []
    for svc in booked_services:
        if not isinstance(svc, dict):
            continue
        normalized.append(
            {
                "name": svc.get("name") or None,
                "audience": svc.get("audience") or None,
                "service_type": svc.get("service_type") or None,
            }
        )

    # If there are no services but spec is non-empty, fail immediately.
    if not normalized and expected:
        return {
            "match": False,
            "mismatches": ["no booked services found to validate against expected spec"],
            "booked_summary": [],
        }

    # --- name_contains ---
    if "name_contains" in expected:
        needle = (expected["name_contains"] or "").strip().lower()
        if needle:
            found = any(
                needle in (svc["name"] or "").lower()
                for svc in normalized
            )
            if not found:
                names = [svc["name"] for svc in normalized]
                mismatches.append(
                    f"name_contains={expected['name_contains']!r} not found in booked "
                    f"service names: {names}"
                )

    # --- audience ---
    if "audience" in expected:
        want_audience = expected["audience"]
        found = any(svc["audience"] == want_audience for svc in normalized)
        if not found:
            audiences = [svc["audience"] for svc in normalized]
            mismatches.append(
                f"audience={want_audience!r} not matched by any booked service "
                f"(got: {audiences})"
            )

    # --- service_type ---
    if "service_type" in expected:
        want_type = expected["service_type"]
        found = any(svc["service_type"] == want_type for svc in normalized)
        if not found:
            types = [svc["service_type"] for svc in normalized]
            mismatches.append(
                f"service_type={want_type!r} not matched by any booked service "
                f"(got: {types})"
            )

    # --- forbidden_audience ---
    if "forbidden_audience" in expected:
        forbidden = expected["forbidden_audience"]
        violators = [
            svc["name"] for svc in normalized if svc["audience"] == forbidden
        ]
        if violators:
            mismatches.append(
                f"forbidden_audience={forbidden!r} found on booked service(s): {violators}"
            )

    return {
        "match": len(mismatches) == 0,
        "mismatches": mismatches,
        "booked_summary": normalized,
    }
