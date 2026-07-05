"""A1/A2 — Unit tests for the gate-flag-timing and step_order checkers in qa_turn_helper.py.

Spec: sdd/qa-loop-conversation-quality — Requirement: Gate-flag-timing check,
Requirement: step_order supersequence assertion.

TDD: written before the checkers exist in qa_turn_helper.py — imports fail (RED)
until A1/A2 add detect_premature_extras_flags()/check_step_order() and their
CLI subcommands.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# A1 — detect_premature_extras_flags()
# ---------------------------------------------------------------------------


def _detect_premature_extras_flags(run: dict) -> dict:
    from tests.e2e.harness.qa_turn_helper import detect_premature_extras_flags

    return detect_premature_extras_flags(run)


def test_front_loaded_flags_on_single_service_request_are_flagged() -> None:
    """GIVEN turn 1's first update_booking call has services=["corte de mujer"]
    WHEN extras_asked=true AND no_more_services=true in that same call
    AND no prior turn shows next_step=extras_loop_required
    THEN the check MUST flag the run.
    """
    run = {
        "scenario_id": "change-a-pre-book-recheck",
        "turns": [
            {
                "turn": 1,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "arguments": {
                            "services": ["corte de mujer"],
                            "extras_asked": True,
                            "no_more_services": True,
                        },
                        "result": {
                            "result_summary": ('{"status":"partial","next_step":"name_required"}')
                        },
                    }
                ],
            }
        ],
    }
    result = _detect_premature_extras_flags(run)
    assert result["scenario_id"] == "change-a-pre-book-recheck"
    assert result["premature_flag_detected"] is True
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["turn"] == 1
    assert finding["services"] == ["corte de mujer"]
    assert finding["extras_asked"] is True
    assert finding["no_more_services"] is True


def test_two_plus_service_fast_path_is_exempt() -> None:
    """GIVEN the first update_booking call lists 2+ services
    WHEN both flags are true in that call
    THEN the check MUST NOT flag the run.
    """
    run = {
        "scenario_id": "fast-path-two-services",
        "turns": [
            {
                "turn": 1,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "arguments": {
                            "services": ["corte de mujer", "tinte"],
                            "extras_asked": True,
                            "no_more_services": True,
                        },
                        "result": {
                            "result_summary": ('{"status":"partial","next_step":"name_required"}')
                        },
                    }
                ],
            }
        ],
    }
    result = _detect_premature_extras_flags(run)
    assert result["premature_flag_detected"] is False
    assert result["findings"] == []


def test_legit_loop_after_extras_loop_required_is_not_flagged() -> None:
    """A first single-service call that already went through extras_loop_required
    (e.g. a re-loop within the same conversation, evidenced by an EARLIER
    tool_evidence item reporting next_step=extras_loop_required before the
    services-introducing call) must NOT be flagged.
    """
    run = {
        "scenario_id": "legit-loop",
        "turns": [
            {
                "turn": 1,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "arguments": {"services": []},
                        "result": {
                            "result_summary": (
                                '{"status":"partial","next_step":"extras_loop_required"}'
                            )
                        },
                    },
                    {
                        "tool_name": "update_booking",
                        "arguments": {
                            "services": ["corte de mujer"],
                            "extras_asked": True,
                            "no_more_services": True,
                        },
                        "result": {
                            "result_summary": ('{"status":"partial","next_step":"name_required"}')
                        },
                    },
                ],
            }
        ],
    }
    result = _detect_premature_extras_flags(run)
    assert result["premature_flag_detected"] is False
    assert result["findings"] == []


def test_missing_turns_key_is_safe() -> None:
    """Malformed/partial run dicts (error outcomes, timeouts) must not raise."""
    result = _detect_premature_extras_flags({"scenario_id": "broken-run"})
    assert result["premature_flag_detected"] is False
    assert result["findings"] == []


def test_no_update_booking_calls_is_safe() -> None:
    run = {
        "scenario_id": "no-tool-calls",
        "turns": [{"turn": 1, "tool_evidence": []}],
    }
    result = _detect_premature_extras_flags(run)
    assert result["premature_flag_detected"] is False
    assert result["findings"] == []


def test_cli_declares_detect_gate_flags_subcommand() -> None:
    from tests.e2e.harness.qa_turn_helper import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["detect-gate-flags", "--run-file", "some-run.json"])
    assert args.command == "detect-gate-flags"
    assert args.run_file == "some-run.json"


# ---------------------------------------------------------------------------
# A2 — check_step_order()
# ---------------------------------------------------------------------------


def _check_step_order(run: dict, expected_order: list[str]) -> dict:
    from tests.e2e.harness.qa_turn_helper import check_step_order

    return check_step_order(run, expected_order)


def test_premature_confirmation_detected() -> None:
    """GIVEN expect.step_order: [policy_acceptance_required, name_required, booking_ready]
    WHEN the observed sequence confirms (booking_ready) BEFORE policy_acceptance_required appears
    THEN the checker MUST FAIL the scenario (out_of_order is reported, not just
    silently absorbed as a subsequence match).
    """
    run = {
        "scenario_id": "premature-confirm",
        "turns": [
            {
                "turn": 1,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"booking_ready"}'},
                    },
                ],
            },
            {
                "turn": 2,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"policy_acceptance_required"}'},
                    },
                ],
            },
        ],
    }
    expected_order = ["policy_acceptance_required", "booking_ready"]
    result = _check_step_order(run, expected_order)
    assert result["step_order_ok"] is False
    assert result["out_of_order"] == "booking_ready"
    assert result["missing_steps"] == []


def test_declared_order_preserved_with_gaps_allowed_passes() -> None:
    """Declared order preserved with extra/unexpected next_steps interleaved (gaps
    allowed) still passes — e.g. a re-validation loop like
    pre_book_validation_required between two declared steps.
    """
    run = {
        "scenario_id": "gaps-allowed",
        "turns": [
            {
                "turn": 1,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"name_required"}'},
                    },
                ],
            },
            {
                "turn": 2,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"notes_optional"}'},
                    },
                ],
            },
            {
                "turn": 3,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {
                            "result_summary": '{"next_step":"pre_book_validation_required"}'
                        },
                    },
                ],
            },
            {
                "turn": 4,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"policy_acceptance_required"}'},
                    },
                ],
            },
            {
                "turn": 5,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"booking_ready"}'},
                    },
                ],
            },
        ],
    }
    expected_order = [
        "name_required",
        "notes_optional",
        "policy_acceptance_required",
        "booking_ready",
    ]
    result = _check_step_order(run, expected_order)
    assert result["step_order_ok"] is True
    assert result["missing_steps"] == []
    assert result["out_of_order"] is None


def test_missing_declared_step_is_reported() -> None:
    """A declared step never observed anywhere is reported in missing_steps
    (not conflated with out_of_order)."""
    run = {
        "scenario_id": "missing-step",
        "turns": [
            {
                "turn": 1,
                "tool_evidence": [
                    {
                        "tool_name": "update_booking",
                        "result": {"result_summary": '{"next_step":"name_required"}'},
                    },
                ],
            },
        ],
    }
    expected_order = ["name_required", "booking_ready"]
    result = _check_step_order(run, expected_order)
    assert result["step_order_ok"] is False
    assert result["missing_steps"] == ["booking_ready"]


def test_malformed_run_is_safe() -> None:
    result = _check_step_order({"scenario_id": "broken"}, ["name_required"])
    assert result["step_order_ok"] is False
    assert result["missing_steps"] == ["name_required"]
    assert result["out_of_order"] is None


def test_cli_declares_check_step_order_subcommand() -> None:
    from tests.e2e.harness.qa_turn_helper import _build_parser

    parser = _build_parser()
    args = parser.parse_args(
        [
            "check-step-order",
            "--run-file",
            "some-run.json",
            "--expected-order",
            '["name_required", "booking_ready"]',
        ]
    )
    assert args.command == "check-step-order"
    assert args.run_file == "some-run.json"
    assert args.expected_order == '["name_required", "booking_ready"]'
