"""Thin CLI wrapper for QA turn operations.

Provides 4 subcommands (health, turn, reset, state) that a Claude Code
sub-agent can call via Bash to drive live conversational QA flows.

Usage:
    python tests/e2e/harness/qa_turn_helper.py health
    python tests/e2e/harness/qa_turn_helper.py turn --conversation-id <uuid> --user-message "Hola"
    python tests/e2e/harness/qa_turn_helper.py reset --conversation-id <uuid>
    python tests/e2e/harness/qa_turn_helper.py state --conversation-id <uuid>
    python tests/e2e/harness/qa_turn_helper.py detect-repeats --run-file <run.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

from shared.config import get_settings
from tests.e2e.harness.redis_harness import RedisTestHarness

# ---------------------------------------------------------------------------
# I5 — Repeated sentence detector (QA post-hoc validator)
# ---------------------------------------------------------------------------


def detect_repeated_sentences(text: str) -> list[str]:
    """Detect sentences that appear two or more times in a bot response.

    Rules (per ADR-I5.1 — detect in QA harness, not in production middleware):
    - Split on sentence-ending punctuation: '.', '!', '?'
    - Strip leading/trailing whitespace from each fragment
    - Flag any sentence that appears >= 2 times AND has > 5 words
    - Short fragments (<= 5 words) are intentionally NOT flagged to avoid
      false positives from common fillers ('Hola.', 'Sí.', 'Ok.', etc.)

    Returns:
        List of sentence strings that are repeated. Empty list if none.

    Usage in run JSON output (T15 wires this into the turn output dict):
        output["repeated_sentences"] = detect_repeated_sentences(agent_response)
    """
    import re

    if not text:
        return []

    # Split on '.', '!', '?' while keeping the delimiter attached
    fragments = re.split(r"(?<=[.!?])\s+", text)

    # Normalize: strip punctuation tails and whitespace, lowercase for comparison
    normalized: list[str] = []
    for frag in fragments:
        cleaned = frag.strip().rstrip(".!?").strip()
        if cleaned:
            normalized.append(cleaned)

    # Count occurrences (case-insensitive)
    counts: dict[str, int] = {}
    originals: dict[str, str] = {}  # lowercase → original casing
    for sentence in normalized:
        key = sentence.lower()
        counts[key] = counts.get(key, 0) + 1
        if key not in originals:
            originals[key] = sentence

    # Flag sentences that appear >= 2x AND have > 5 words
    repeated = [
        originals[key]
        for key, count in counts.items()
        if count >= 2 and len(originals[key].split()) > 5
    ]

    return repeated


def detect_repeats_in_run(run: dict) -> dict:
    """Scan a full run JSON dict and report repeated sentences per turn (L5).

    Auditor entry point (Change L wires the I5 detector into the audit
    pipeline): the qa-auditor calls this over every scenario run file and
    reports non-empty findings as WARN items in audit.md.

    Tolerates partial/malformed run dicts (error outcomes, timeouts): missing
    `turns` and null `agent_response` values are skipped, never raised on.

    Returns:
        {
          "scenario_id": str | None,
          "turns_with_repeats": int,
          "findings": [{"turn": int | None, "repeated_sentences": [str, ...]}, ...]
        }
    """
    findings: list[dict[str, Any]] = []
    for turn in run.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        repeated = detect_repeated_sentences(turn.get("agent_response") or "")
        if repeated:
            findings.append({"turn": turn.get("turn"), "repeated_sentences": repeated})
    return {
        "scenario_id": run.get("scenario_id"),
        "turns_with_repeats": len(findings),
        "findings": findings,
    }


def _extract_next_step_from_evidence(item: dict) -> str | None:
    """Extract `next_step` from a single tool_evidence item, tolerating shape drift.

    Primary shape (raw harness output): `result.result_summary` is a JSON
    **string** produced by the tool's `ToolResponse.model_dump_json()`; parse it
    and read `next_step`.

    Fallback shape (some curated/manual run files): `result_next_step` sits
    directly on the item. Tolerated for robustness; not the primary contract.
    """
    result = item.get("result")
    if isinstance(result, dict):
        summary = result.get("result_summary")
        if isinstance(summary, str):
            try:
                parsed = json.loads(summary)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if isinstance(parsed, dict) and "next_step" in parsed:
                return parsed.get("next_step")

    fallback = item.get("result_next_step")
    if isinstance(fallback, str):
        return fallback

    return None


# ---------------------------------------------------------------------------
# A1 — Gate-flag-timing checker (findings #2/#3)
# ---------------------------------------------------------------------------


def detect_premature_extras_flags(run: dict) -> dict:
    """Flag a run whose FIRST services-introducing `update_booking` call sets
    `extras_asked`/`no_more_services` before the extras loop legitimately fired.

    Rules (Requirement: Gate-flag-timing check):
    - Walk turns in order; find the FIRST `update_booking` tool_evidence item
      whose `arguments` carry a non-empty `services` list (the call that
      INTRODUCES services). Because `update_booking` is stateless (R20), later
      calls legitimately re-pass the flags — so ONLY the first
      services-introducing call is inspected (matches the tool's own gate at
      update_booking.py:678, `len(services)>=1 and not both flags`).
    - Flag when: `len(services) == 1` AND (`extras_asked is True` OR
      `no_more_services is True`) AND no EARLIER tool_evidence item (before the
      introducing call) evidenced `next_step=extras_loop_required`.
    - The 2+-service fast path (`len(services) >= 2`) is EXEMPT (booking_flow
      Paso 3 legitimate path) — never flagged, regardless of the flags' values.

    Tolerates malformed/partial run dicts (error outcomes, timeouts): missing
    `turns`, non-dict turns/items, and missing `arguments` are skipped, never
    raised on.

    Returns:
        {
          "scenario_id": str | None,
          "premature_flag_detected": bool,
          "findings": [{"turn": int | None, "services": [...],
                        "extras_asked": bool, "no_more_services": bool}, ...]
        }
    """
    findings: list[dict[str, Any]] = []
    premature_detected = False
    seen_extras_loop_required = False
    introducing_found = False

    for turn in run.get("turns") or []:
        if introducing_found:
            break
        if not isinstance(turn, dict):
            continue
        turn_num = turn.get("turn")
        for item in turn.get("tool_evidence") or []:
            if not isinstance(item, dict):
                continue
            if item.get("tool_name") != "update_booking":
                continue

            arguments = item.get("arguments")
            services = arguments.get("services") if isinstance(arguments, dict) else None

            if isinstance(services, list) and len(services) >= 1:
                introducing_found = True
                if len(services) == 1:
                    extras_asked = bool(arguments.get("extras_asked"))
                    no_more_services = bool(arguments.get("no_more_services"))
                    if (extras_asked or no_more_services) and not seen_extras_loop_required:
                        premature_detected = True
                        findings.append(
                            {
                                "turn": turn_num,
                                "services": services,
                                "extras_asked": extras_asked,
                                "no_more_services": no_more_services,
                            }
                        )
                break  # introducing call found — stop scanning this run

            next_step = _extract_next_step_from_evidence(item)
            if next_step == "extras_loop_required":
                seen_extras_loop_required = True

    return {
        "scenario_id": run.get("scenario_id"),
        "premature_flag_detected": premature_detected,
        "findings": findings,
    }


def _find_step_from(
    observed: list[str], step: str, start: int, end: int | None = None
) -> int | None:
    """Return the index of the first occurrence of `step` in observed[start:end], or None."""
    stop = end if end is not None else len(observed)
    for i in range(start, stop):
        if observed[i] == step:
            return i
    return None


# ---------------------------------------------------------------------------
# A2 — step_order supersequence assertion (finding #3, premature confirmation)
# ---------------------------------------------------------------------------


def check_step_order(run: dict, expected_order: list[str]) -> dict:
    """Assert the observed `next_step` sequence contains `expected_order` as an
    ordered subsequence (order preserved, gaps allowed).

    Observed sequence: for each turn, in order, extract `next_step` from every
    `tool_evidence` item (see `_extract_next_step_from_evidence`), dropping
    `None` and collapsing consecutive duplicates.

    Catches premature confirmation: if a declared step (e.g. `booking_ready`)
    is observed only BEFORE an earlier-declared step (e.g.
    `policy_acceptance_required`) is matched, the subsequence match fails and
    the step is reported in `out_of_order` (distinct from `missing_steps`,
    which are declared steps never observed anywhere in the run).

    Tolerates malformed/partial run dicts — missing `turns` yields an empty
    observed sequence, so every declared step is reported as missing.

    Returns:
        {
          "scenario_id": str | None,
          "expected_order": [...],
          "observed_order": [...],
          "step_order_ok": bool,
          "missing_steps": [...],   # declared steps never observed
          "out_of_order": str | None,  # first declared step found out of order
        }
    """
    observed: list[str] = []
    for turn in run.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        for item in turn.get("tool_evidence") or []:
            if not isinstance(item, dict):
                continue
            next_step = _extract_next_step_from_evidence(item)
            if next_step is None:
                continue
            if not observed or observed[-1] != next_step:
                observed.append(next_step)

    step_order_ok = True
    missing_steps: list[str] = []
    out_of_order: str | None = None
    idx = 0

    for step in expected_order:
        pos = _find_step_from(observed, step, idx)
        if pos is not None:
            idx = pos + 1
            continue

        step_order_ok = False
        earlier_pos = _find_step_from(observed, step, 0, idx)
        if earlier_pos is not None:
            if out_of_order is None:
                out_of_order = step
        else:
            missing_steps.append(step)

    return {
        "scenario_id": run.get("scenario_id"),
        "expected_order": expected_order,
        "observed_order": observed,
        "step_order_ok": step_order_ok,
        "missing_steps": missing_steps,
        "out_of_order": out_of_order,
    }


def compute_l4_verdict(
    hallucination_result: dict[str, Any],
    service_match: dict[str, Any] | None,
    consent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the combined L4 verdict from hallucination, service-match, and consent results.

    Pure function — no I/O, no DB. Factored out so unit tests can cover verdict
    logic without needing a DB or async context.

    Args:
        hallucination_result: Output of detect_unbacked_confirmation().
            Required keys: "hallucinated_confirmation" (bool), "matched_phrase" (str|None).
        service_match: Output of check_service_match(), or None when not asserted.
            When None, service match is treated as passing (not asserted).
        consent: Optional consent assertion dict. When None, consent is not asserted.
            Shape: {"expected": bool, "consent_ok": bool, "consent_info": {...}}.
            l4_pass fails only when expected=True and consent_ok=False.

    Returns:
        {
            "l4_pass": bool,
            "findings": list[str],  # human-readable failure reasons; empty when passing
        }
    """
    findings: list[str] = []

    if hallucination_result.get("hallucinated_confirmation"):
        phrase = hallucination_result.get("matched_phrase")
        findings.append(
            f"hallucinated confirmation: bot claimed booking confirmed but no appointment "
            f"exists in DB (matched phrase: {phrase!r})"
        )

    if service_match is not None and not service_match.get("match"):
        for mismatch in service_match.get("mismatches") or []:
            findings.append(f"service mismatch: {mismatch}")

    if consent is not None and consent.get("expected") and not consent.get("consent_ok"):
        info = consent.get("consent_info") or {}
        findings.append(
            f"consent not persisted: policy_accepted_at={info.get('policy_accepted_at')!r}, "
            f"customer_consents rows={info.get('consent_rows', 0)} "
            f"(expected a stored consent)"
        )

    return {
        "l4_pass": len(findings) == 0,
        "findings": findings,
    }


async def _cmd_service_check(args: Any) -> None:
    """Fetch the booked services for a phone's latest (or given) appointment and validate them.

    Queries:
        SELECT a.id, a.service_ids
        FROM appointments a
        JOIN customers c ON c.id = a.customer_id
        WHERE c.phone = :phone
          [AND a.id = :appointment_id]
        ORDER BY a.start_time DESC
        LIMIT 1

    Then resolves each service UUID to (name, audience, service_type) via the services table
    and calls check_service_match against the --expected-json spec.
    """

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from tests.e2e.harness.assert_service_match import check_service_match

    try:
        expected = json.loads(args.expected_json)
    except (json.JSONDecodeError, TypeError) as exc:
        _json_err("invalid_expected_json", str(exc))
        return

    if not isinstance(expected, dict):
        _json_err("invalid_expected_json", "expected-json must be a JSON object")
        return

    settings = get_settings()
    db_url = str(settings.DATABASE_URL)
    # SQLAlchemy async engine requires asyncpg driver
    if db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
            "postgresql+psycopg://", "postgresql+asyncpg://", 1
        )

    engine = create_async_engine(db_url, echo=False)
    try:
        async with AsyncSession(engine) as session:
            # Resolve appointment: latest for phone, or specific by id
            if args.appointment_id:
                appt_row = await session.execute(
                    text(
                        "SELECT a.id, a.service_ids "
                        "FROM appointments a "
                        "JOIN customers c ON c.id = a.customer_id "
                        "WHERE c.phone = :phone AND a.id = :appt_id "
                        "LIMIT 1"
                    ),
                    {"phone": args.phone, "appt_id": args.appointment_id},
                )
            else:
                appt_row = await session.execute(
                    text(
                        "SELECT a.id, a.service_ids "
                        "FROM appointments a "
                        "JOIN customers c ON c.id = a.customer_id "
                        "WHERE c.phone = :phone "
                        "ORDER BY a.start_time DESC "
                        "LIMIT 1"
                    ),
                    {"phone": args.phone},
                )
            appt = appt_row.fetchone()

            if appt is None:
                _json_out(
                    {
                        "phone": args.phone,
                        "appointment_id": None,
                        "booked_services": [],
                        "expected": expected,
                        "result": {
                            "match": False,
                            "mismatches": ["no appointment found for phone"],
                            "booked_summary": [],
                        },
                    }
                )
                return

            appointment_id = str(appt[0])
            service_ids: list = appt[1] or []

            # Resolve service UUIDs to (name, audience, service_type)
            booked_services: list[dict[str, Any]] = []
            if service_ids:
                # Cast UUIDs to text for the IN clause
                id_params = {f"sid_{i}": str(sid) for i, sid in enumerate(service_ids)}
                placeholders = ", ".join(f":sid_{i}" for i in range(len(service_ids)))
                svc_rows = await session.execute(
                    text(
                        f"SELECT name, audience, metadata->>'service_type' AS service_type "
                        f"FROM services WHERE id::text IN ({placeholders})"
                    ),
                    id_params,
                )
                for row in svc_rows.fetchall():
                    booked_services.append(
                        {
                            "name": row[0],
                            "audience": row[1],
                            "service_type": row[2],
                        }
                    )

            result = check_service_match(booked_services, expected)
            _json_out(
                {
                    "phone": args.phone,
                    "appointment_id": appointment_id,
                    "booked_services": booked_services,
                    "expected": expected,
                    "result": result,
                }
            )
    except Exception as exc:
        _json_err("service_check_failed", str(exc))
    finally:
        await engine.dispose()


async def _cmd_reconcile(args: Any) -> None:
    """Reconcile agent claim vs backend: combines hallucination check + service validation.

    Queries the DB for the latest appointment for the given phone, loads the run JSON,
    and produces a combined L4 verdict (hallucinated_confirmation + service_match).

    Exit codes: 0 = l4_pass True; 1 = error; 3 = l4_pass False.
    """
    from pathlib import Path

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from tests.e2e.harness.assert_claim_backend import detect_unbacked_confirmation
    from tests.e2e.harness.assert_service_match import check_service_match

    # --- Load run file ---
    run_path = Path(args.run_file)
    if not run_path.exists():
        _json_err("run_file_not_found", args.run_file)
        return
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _json_err("run_file_unreadable", str(exc))
        return
    if not isinstance(run, dict):
        _json_err("run_file_invalid", "top-level JSON must be an object")
        return

    # --- Parse optional expected-service-json ---
    expected_spec: dict[str, Any] | None = None
    if args.expected_service_json:
        try:
            expected_spec = json.loads(args.expected_service_json)
        except (json.JSONDecodeError, TypeError) as exc:
            _json_err("invalid_expected_service_json", str(exc))
            return
        if not isinstance(expected_spec, dict):
            _json_err("invalid_expected_service_json", "must be a JSON object")
            return

    # --- DB query: latest appointment for phone ---
    settings = get_settings()
    db_url = str(settings.DATABASE_URL)
    if db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
            "postgresql+psycopg://", "postgresql+asyncpg://", 1
        )

    appointment_id: str | None = None
    appointment_status: str | None = None
    booked_services: list[dict[str, Any]] = []
    appointment_exists: bool = False
    consent_info: dict[str, Any] = {
        "policy_accepted_at": None,
        "policy_version": None,
        "consent_rows": 0,
    }

    engine = create_async_engine(db_url, echo=False)
    try:
        async with AsyncSession(engine) as session:
            appt_row = await session.execute(
                text(
                    "SELECT a.id, a.status, a.service_ids "
                    "FROM appointments a "
                    "JOIN customers c ON c.id = a.customer_id "
                    "WHERE c.phone = :phone "
                    "ORDER BY a.start_time DESC "
                    "LIMIT 1"
                ),
                {"phone": args.phone},
            )
            appt = appt_row.fetchone()

            if appt is not None:
                appointment_exists = True
                appointment_id = str(appt[0])
                appointment_status = str(appt[1]) if appt[1] is not None else None
                service_ids: list = appt[2] or []

                if service_ids:
                    id_params = {f"sid_{i}": str(sid) for i, sid in enumerate(service_ids)}
                    placeholders = ", ".join(f":sid_{i}" for i in range(len(service_ids)))
                    svc_rows = await session.execute(
                        text(
                            f"SELECT name, audience, metadata->>'service_type' AS service_type "
                            f"FROM services WHERE id::text IN ({placeholders})"
                        ),
                        id_params,
                    )
                    for row in svc_rows.fetchall():
                        booked_services.append(
                            {
                                "name": row[0],
                                "audience": row[1],
                                "service_type": row[2],
                            }
                        )

            # Consent check: query the DB as source of truth regardless of appointment.
            # Uses customers.policy_accepted_at + COUNT(customer_consents rows).
            # When the phone has no customer row, defaults to null/0 (no error).
            #
            # SELECT c.policy_accepted_at, c.policy_version,
            #        COUNT(cc.id) AS consent_rows
            # FROM customers c
            # LEFT JOIN customer_consents cc ON cc.customer_id = c.id
            # WHERE c.phone = :phone
            # GROUP BY c.policy_accepted_at, c.policy_version
            consent_row = await session.execute(
                text(
                    "SELECT c.policy_accepted_at, c.policy_version, "
                    "COUNT(cc.id) AS consent_rows "
                    "FROM customers c "
                    "LEFT JOIN customer_consents cc ON cc.customer_id = c.id "
                    "WHERE c.phone = :phone "
                    "GROUP BY c.policy_accepted_at, c.policy_version"
                ),
                {"phone": args.phone},
            )
            crow = consent_row.fetchone()
            if crow is not None:
                consent_info = {
                    "policy_accepted_at": crow[0].isoformat() if crow[0] is not None else None,
                    "policy_version": crow[1],
                    "consent_rows": int(crow[2]),
                }
    except Exception as exc:
        _json_err("db_query_failed", str(exc))
        return
    finally:
        await engine.dispose()

    # --- Collect agent messages from run JSON ---
    agent_messages: list[str] = [
        t["agent_response"]
        for t in (run.get("turns") or [])
        if isinstance(t, dict) and isinstance(t.get("agent_response"), str) and t["agent_response"]
    ]

    # --- Hallucination check ---
    hallucination_result = detect_unbacked_confirmation(agent_messages, appointment_exists)

    # --- Service match (only if spec provided AND appointment exists) ---
    service_match: dict[str, Any] | None = None
    if expected_spec is not None and appointment_exists:
        service_match = check_service_match(booked_services, expected_spec)

    # --- Consent assertion (only when --expect-consent is set) ---
    consent_ok: bool = (
        consent_info["policy_accepted_at"] is not None and consent_info["consent_rows"] >= 1
    )
    consent_arg: dict[str, Any] | None = None
    if args.expect_consent:
        consent_arg = {
            "expected": True,
            "consent_ok": consent_ok,
            "consent_info": consent_info,
        }

    # --- Combined L4 verdict ---
    verdict = compute_l4_verdict(hallucination_result, service_match, consent=consent_arg)

    _json_out(
        {
            "phone": args.phone,
            "run_file": args.run_file,
            "appointment_exists": appointment_exists,
            "appointment_id": appointment_id,
            "appointment_status": appointment_status,
            "booked_services": booked_services,
            "hallucinated_confirmation": hallucination_result["hallucinated_confirmation"],
            "matched_phrase": hallucination_result.get("matched_phrase"),
            "service_match": service_match,
            "consent_info": consent_info,
            "consent_ok": consent_ok,
            "l4_pass": verdict["l4_pass"],
            "findings": verdict["findings"],
        }
    )

    if not verdict["l4_pass"]:
        sys.exit(3)


def _cmd_detect_repeats(run_file: str) -> None:
    """Load a run JSON file and print the repeated-sentence report."""
    from pathlib import Path

    path = Path(run_file)
    if not path.exists():
        _json_err("run_file_not_found", run_file)
        return
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _json_err("run_file_unreadable", str(exc))
        return
    _json_out(detect_repeats_in_run(run))


def _cmd_detect_gate_flags(run_file: str) -> None:
    """Load a run JSON file and print the gate-flag-timing report (A1)."""
    from pathlib import Path

    path = Path(run_file)
    if not path.exists():
        _json_err("run_file_not_found", run_file)
        return
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _json_err("run_file_unreadable", str(exc))
        return
    _json_out(detect_premature_extras_flags(run))


def _cmd_check_step_order(run_file: str, expected_order_json: str) -> None:
    """Load a run JSON file + expected step order and print the step_order report (A2)."""
    from pathlib import Path

    path = Path(run_file)
    if not path.exists():
        _json_err("run_file_not_found", run_file)
        return
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _json_err("run_file_unreadable", str(exc))
        return
    try:
        expected_order = json.loads(expected_order_json)
    except (json.JSONDecodeError, TypeError) as exc:
        _json_err("invalid_expected_order", str(exc))
        return
    if not isinstance(expected_order, list):
        _json_err("invalid_expected_order", "--expected-order must be a JSON list")
        return
    _json_out(check_step_order(run, expected_order))


def _json_out(data: dict[str, Any]) -> None:
    """Write JSON to stdout and exit 0."""
    print(json.dumps(data, ensure_ascii=False, default=str))


def _json_err(error: str, details: str | None = None) -> None:
    """Write error JSON to stderr and exit 1."""
    payload: dict[str, Any] = {"ok": False, "error": error}
    if details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


async def _cmd_health() -> None:
    """Check Redis connectivity and INCOMING_STREAM existence."""
    import redis.asyncio as redis

    from shared.config import get_settings
    from shared.redis_client import INCOMING_STREAM

    settings = get_settings()
    redis_kwargs: dict[str, Any] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        redis_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs)
    try:
        await client.ping()
        stream_exists = await client.exists(INCOMING_STREAM)
        _json_out(
            {
                "ok": True,
                "redis": "connected",
                "stream": "exists" if stream_exists else "missing",
            }
        )
    except Exception as exc:
        _json_err("redis_connection_failed", str(exc))
    finally:
        await client.aclose()


async def _cmd_turn(args: Any) -> int:
    """Execute an atomic subscribe-before-inject turn.

    Builds QARunIdentity and QARunSession from CLI args, then delegates
    to RedisTestHarness.execute_turn(). Returns 0 on success, 2 on timeout.
    """
    import redis.asyncio as redis

    from tests.e2e.harness.run_models import QARunIdentity, QARunSession

    settings = get_settings()
    redis_kwargs: dict[str, Any] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        redis_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs)
    harness = RedisTestHarness(redis_client=client)
    try:
        identity = QARunIdentity(
            conversation_id=args.conversation_id,
            customer_phone=args.customer_phone,
            sender_name=args.persona_name,
            run_started_at=datetime.now(UTC),
        )
        session = QARunSession(
            identity=identity,
            started_monotonic=time.monotonic(),
        )
        result = await harness.execute_turn(
            user_message=args.user_message,
            session=session,
            timeout=args.timeout,
            raise_on_timeout=False,
        )
        _json_out(
            {
                "agent_response": result["agent_response"],
                "timed_out": result["timed_out"],
                "response_latency_ms": result["response_latency_ms"],
                "tool_evidence": result["tool_evidence"],
            }
        )
        return 2 if result["timed_out"] else 0
    except Exception as exc:
        _json_err("turn_failed", str(exc))
        return 1
    finally:
        await harness.close()
        await client.aclose()


async def _cmd_burst(args: Any) -> int:
    """Execute a burst of messages as a single logical turn.

    All messages are injected in order within the agent's batch window so the
    agent merges them into ONE turn and produces ONE coherent reply.

    Returns 0 on success, 2 on timeout.
    """
    import redis.asyncio as redis

    from tests.e2e.harness.run_models import QARunIdentity, QARunSession

    settings = get_settings()
    redis_kwargs: dict[str, Any] = {"decode_responses": True}
    if settings.REDIS_PASSWORD:
        redis_kwargs["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs)
    harness = RedisTestHarness(redis_client=client)
    try:
        identity = QARunIdentity(
            conversation_id=args.conversation_id,
            customer_phone=args.customer_phone,
            sender_name=args.persona_name,
            run_started_at=datetime.now(UTC),
        )
        session = QARunSession(
            identity=identity,
            started_monotonic=time.monotonic(),
        )
        result = await harness.execute_burst_turn(
            user_messages=args.user_message,
            session=session,
            timeout=args.timeout,
            inter_message_delay=args.inter_message_delay,
            raise_on_timeout=False,
        )
        _json_out(
            {
                "agent_response": result["agent_response"],
                "timed_out": result["timed_out"],
                "response_latency_ms": result["response_latency_ms"],
                "tool_evidence": result["tool_evidence"],
                "burst_messages": result["burst_messages"],
                "burst_size": result["burst_size"],
            }
        )
        return 2 if result["timed_out"] else 0
    except Exception as exc:
        _json_err("burst_failed", str(exc))
        return 1
    finally:
        await harness.close()
        await client.aclose()


async def _cmd_seed_appointment(args: Any) -> None:
    """Seed a future appointment for notification worker QA testing."""
    from tests.e2e.harness.seed_customer import seed_future_appointment

    try:
        result = await seed_future_appointment(
            phone=args.phone,
            customer_name=args.customer_name,
            hours_ahead=args.hours_ahead,
            status=args.status,
            service_name=args.service_name or None,
            stylist_name=args.stylist_name or None,
        )
        _json_out(result)
    except ValueError as exc:
        _json_err("phone_guard_failed", str(exc))
    except RuntimeError as exc:
        _json_err("seed_failed", str(exc))
    except Exception as exc:
        _json_err("seed_failed", str(exc))


async def _cmd_seed(args: Any) -> None:
    """Seed a returning customer with memories and an optional past appointment."""
    from tests.e2e.harness.seed_customer import seed_returning_customer

    try:
        memories = json.loads(args.memories_json)
    except json.JSONDecodeError as exc:
        _json_err("invalid memories_json", str(exc))
        return

    past_appt: dict | None = None
    if args.past_appointment_json:
        try:
            past_appt = json.loads(args.past_appointment_json)
        except json.JSONDecodeError as exc:
            _json_err("invalid past_appointment_json", str(exc))
            return

    try:
        result = await seed_returning_customer(
            phone=args.phone,
            customer_name=args.customer_name,
            memories=memories,
            past_appointment=past_appt,
        )
        _json_out(result)
    except ValueError as exc:
        _json_err("phone_guard_failed", str(exc))
    except Exception as exc:
        _json_err("seed_failed", str(exc))


async def _cmd_reset(conversation_id: str, phone: str) -> None:
    """Clean up Redis state for a conversation."""
    import redis.asyncio as redis

    from shared.config import get_settings
    from tests.e2e.harness.state_reset import StateResetHarness

    settings = get_settings()
    redis_kwargs_bin: dict[str, Any] = {"decode_responses": False}
    if settings.REDIS_PASSWORD:
        redis_kwargs_bin["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs_bin)
    harness = StateResetHarness(redis_client=client)
    try:
        result = await harness.reset_conversation_state(
            conversation_id=conversation_id,
            customer_phone=phone,
        )
        _json_out(result)
    except Exception as exc:
        _json_err("reset_failed", str(exc))
    finally:
        await client.aclose()


async def _cmd_state(args: Any) -> None:
    """Fetch current checkpoint state for a conversation.

    Outputs only fields present in the current AgentState schema
    (post create_agent rewrite). Does NOT output deleted fields:
    current_mode, mode_context, mode_history, is_first_interaction,
    error_count, booking_step.
    """
    import redis.asyncio as redis
    from langchain_core.messages import ToolMessage

    settings = get_settings()
    redis_kwargs_txt: dict[str, Any] = {"decode_responses": True}
    redis_kwargs_bin2: dict[str, Any] = {"decode_responses": False}
    if settings.REDIS_PASSWORD:
        redis_kwargs_txt["password"] = settings.REDIS_PASSWORD
        redis_kwargs_bin2["password"] = settings.REDIS_PASSWORD
    client = redis.from_url(settings.REDIS_URL, **redis_kwargs_txt)
    binary_client = redis.from_url(settings.REDIS_URL, **redis_kwargs_bin2)
    harness = RedisTestHarness(redis_client=client, binary_redis_client=binary_client)
    try:
        state = await harness.capture_final_state(args.conversation_id)
        if state is None:
            _json_out({"has_checkpoint": False})
            return

        messages = state.get("messages", [])

        # Find the name of the last ToolMessage in the messages list
        latest_tool_call_name: str | None = None
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                latest_tool_call_name = getattr(msg, "name", None)
                break

        _json_out(
            {
                "has_checkpoint": True,
                "conversation_id": state.get("conversation_id"),
                "customer_phone": state.get("customer_phone"),
                "customer_id": state.get("customer_id"),
                "customer_name": state.get("customer_name"),
                "messages_count": len(messages),
                "latest_tool_call_name": latest_tool_call_name,
                "customer_consents_count": len(state.get("customer_consents", []) or []),
                "policy_accepted_at": state.get("policy_accepted_at"),
                "summary_present": bool(state.get("conversation_summary") or state.get("summary")),
            }
        )
    except Exception as exc:
        _json_err("state_fetch_failed", str(exc))
    finally:
        await harness.close()
        await client.aclose()
        await binary_client.aclose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa_turn_helper",
        description="CLI helper for QA conversational turn operations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # health
    sub.add_parser("health", help="Check Redis connectivity")

    # turn
    p_turn = sub.add_parser("turn", help="Execute an atomic conversation turn")
    p_turn.add_argument(
        "--conversation-id", required=True, dest="conversation_id", help="Conversation UUID"
    )
    p_turn.add_argument(
        "--user-message", required=True, dest="user_message", help="User message text"
    )
    p_turn.add_argument(
        "--customer-phone",
        default="+34999000000",
        dest="customer_phone",
        help="Customer phone (must start with TEST_PHONE_PREFIX)",
    )
    p_turn.add_argument(
        "--persona-name",
        default="QA Test Client",
        dest="persona_name",
        help="Customer display name",
    )
    p_turn.add_argument("--timeout", type=float, default=60.0, help="Response timeout (seconds)")

    # reset
    p_reset = sub.add_parser("reset", help="Reset Redis state for a conversation")
    p_reset.add_argument(
        "--conversation-id", required=True, dest="conversation_id", help="Conversation UUID"
    )
    p_reset.add_argument("--phone", default="+34999000000", help="Customer phone")

    # state
    p_state = sub.add_parser("state", help="Fetch checkpoint state")
    p_state.add_argument(
        "--conversation-id", required=True, dest="conversation_id", help="Conversation UUID"
    )

    # burst
    p_burst = sub.add_parser(
        "burst",
        help="Inject multiple messages as one logical burst turn (agent merges them)",
    )
    p_burst.add_argument(
        "--conversation-id", required=True, dest="conversation_id", help="Conversation UUID"
    )
    p_burst.add_argument(
        "--user-message",
        action="append",
        required=True,
        dest="user_message",
        metavar="MESSAGE",
        help="A message in the burst (repeat for each message, in order)",
    )
    p_burst.add_argument(
        "--customer-phone",
        default="+34999000000",
        dest="customer_phone",
        help="Customer phone (must start with TEST_PHONE_PREFIX)",
    )
    p_burst.add_argument(
        "--persona-name",
        default="QA Test Client",
        dest="persona_name",
        help="Customer display name",
    )
    p_burst.add_argument("--timeout", type=float, default=90.0, help="Response timeout (seconds)")
    p_burst.add_argument(
        "--inter-message-delay",
        type=float,
        default=0.4,
        dest="inter_message_delay",
        help="Seconds between consecutive injections (must be < MESSAGE_BATCH_WINDOW_SECONDS)",
    )

    # seed
    p_seed = sub.add_parser(
        "seed",
        help="Seed a returning customer with memories and an optional past appointment",
    )
    p_seed.add_argument("--phone", required=True, help="Customer phone (must start with +349)")
    p_seed.add_argument(
        "--customer-name",
        required=True,
        dest="customer_name",
        help="Full customer name (e.g. 'Ana Torres')",
    )
    p_seed.add_argument(
        "--memories-json",
        required=True,
        dest="memories_json",
        help="JSON object string with memory fields (visit_count, preferred_stylist_name, etc.)",
    )
    p_seed.add_argument(
        "--past-appointment-json",
        default=None,
        dest="past_appointment_json",
        help=("Optional JSON object with keys: days_ago, service_name, stylist_name, status"),
    )

    # seed-appointment — future appointment for notification worker QA
    p_seedappt = sub.add_parser(
        "seed-appointment",
        help=(
            "Seed a future appointment (now + --hours-ahead) for notification worker QA. "
            "Phone must start with TEST_PHONE_PREFIX."
        ),
    )
    p_seedappt.add_argument(
        "--phone", required=True, help="Customer phone (E.164, must start with +349)"
    )
    p_seedappt.add_argument(
        "--customer-name",
        required=True,
        dest="customer_name",
        help="Full customer name (e.g. 'Test User')",
    )
    p_seedappt.add_argument(
        "--hours-ahead",
        required=True,
        type=float,
        dest="hours_ahead",
        help=(
            "Hours from now(UTC) for the appointment start. "
            "Use 24 for reminder_24h window (23–25 h), 48 for confirm_48h window (47–49 h)."
        ),
    )
    p_seedappt.add_argument(
        "--status",
        default="confirmed",
        choices=["confirmed", "pending"],
        help="AppointmentStatus (confirm_48h handler only queries 'pending').",
    )
    p_seedappt.add_argument(
        "--service-name",
        default=None,
        dest="service_name",
        help="Service name (case-insensitive). Falls back to first DB row when omitted.",
    )
    p_seedappt.add_argument(
        "--stylist-name",
        default=None,
        dest="stylist_name",
        help="Stylist name (case-insensitive). Falls back to first DB row when omitted.",
    )

    # detect-repeats (L5 — auditor entry point for the repeated-sentence detector)
    p_repeats = sub.add_parser(
        "detect-repeats", help="Report repeated sentences in a scenario run JSON file"
    )
    p_repeats.add_argument(
        "--run-file", required=True, dest="run_file", help="Path to {scenario_id}.json run file"
    )

    # detect-gate-flags (A1 — gate-flag-timing checker: findings #2/#3)
    p_gateflags = sub.add_parser(
        "detect-gate-flags",
        help="Report premature extras_asked/no_more_services flags in a scenario run JSON file",
    )
    p_gateflags.add_argument(
        "--run-file", required=True, dest="run_file", help="Path to {scenario_id}.json run file"
    )

    # check-step-order (A2 — step_order supersequence assertion: finding #3)
    p_steporder = sub.add_parser(
        "check-step-order",
        help="Assert the observed next_step sequence contains --expected-order as a subsequence",
    )
    p_steporder.add_argument(
        "--run-file", required=True, dest="run_file", help="Path to {scenario_id}.json run file"
    )
    p_steporder.add_argument(
        "--expected-order",
        required=True,
        dest="expected_order",
        help='JSON list of next_step values in declared order, e.g. \'["name_required", "booking_ready"]\'',
    )

    # service-check — deterministic service-type / audience validation
    p_svc = sub.add_parser(
        "service-check",
        help=(
            "Validate that the booked service for a phone matches the expected "
            "service type and audience. Queries the DB for the latest appointment."
        ),
    )
    p_svc.add_argument(
        "--phone",
        required=True,
        help="Customer phone (E.164, must start with TEST_PHONE_PREFIX)",
    )
    p_svc.add_argument(
        "--expected-json",
        required=True,
        dest="expected_json",
        help=(
            "JSON object with optional keys: name_contains, audience, service_type, "
            'forbidden_audience. E.g. \'{"name_contains": "corte", "audience": "adult_female"}\''
        ),
    )
    p_svc.add_argument(
        "--appointment-id",
        default=None,
        dest="appointment_id",
        help="Specific appointment UUID to check (default: latest for the phone)",
    )

    # reconcile — combined L4 claim-vs-backend verdict
    p_rec = sub.add_parser(
        "reconcile",
        help=(
            "Reconcile agent claims vs backend: detects hallucinated confirmations and "
            "validates booked service type/audience. Produces a combined L4 verdict."
        ),
    )
    p_rec.add_argument(
        "--run-file",
        required=True,
        dest="run_file",
        help="Path to the scenario run JSON file",
    )
    p_rec.add_argument(
        "--phone",
        required=True,
        help="Customer phone (E.164, must start with TEST_PHONE_PREFIX)",
    )
    p_rec.add_argument(
        "--expected-service-json",
        default=None,
        dest="expected_service_json",
        help=(
            "Optional JSON object for check_service_match expected spec. "
            "Keys: name_contains, audience, service_type, forbidden_audience. "
            "When omitted, service match is not asserted."
        ),
    )
    p_rec.add_argument(
        "--expect-consent",
        action="store_true",
        default=False,
        dest="expect_consent",
        help=(
            "When set, the reconcile check asserts that policy consent was persisted in "
            "the DB (policy_accepted_at IS NOT NULL and at least one customer_consents row). "
            "Uses the DB as source of truth, not the LangGraph checkpoint."
        ),
    )

    return parser


def main() -> None:
    # Force batch window to 0 so messages are processed immediately
    os.environ["MESSAGE_BATCH_WINDOW_SECONDS"] = "0"

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "health":
        asyncio.run(_cmd_health())
    elif args.command == "turn":
        asyncio.run(_cmd_turn(args))
    elif args.command == "burst":
        sys.exit(asyncio.run(_cmd_burst(args)))
    elif args.command == "reset":
        asyncio.run(
            _cmd_reset(
                conversation_id=args.conversation_id,
                phone=args.phone,
            )
        )
    elif args.command == "state":
        asyncio.run(_cmd_state(args))
    elif args.command == "seed":
        asyncio.run(_cmd_seed(args))
    elif args.command == "seed-appointment":
        asyncio.run(_cmd_seed_appointment(args))
    elif args.command == "detect-repeats":
        _cmd_detect_repeats(args.run_file)
    elif args.command == "detect-gate-flags":
        _cmd_detect_gate_flags(args.run_file)
    elif args.command == "check-step-order":
        _cmd_check_step_order(args.run_file, args.expected_order)
    elif args.command == "service-check":
        asyncio.run(_cmd_service_check(args))
    elif args.command == "reconcile":
        asyncio.run(_cmd_reconcile(args))


if __name__ == "__main__":
    main()
