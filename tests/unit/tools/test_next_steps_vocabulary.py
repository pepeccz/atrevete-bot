"""RED test — T2: NextStep vocabulary + descriptive lint.

Fails on master (module absent). Passes after next_steps.py is created.
Refs: R9, R10, R19
"""

from __future__ import annotations

import io
import pathlib
import tokenize

import pytest

EXPECTED_NEXT_STEP_VALUES = {
    "service_required",
    "stylist_required",
    "date_required",
    "audience_required",
    "advance_policy_violated",
    "confirmation_required",
    "incomplete_booking",
    "booking_ready",
    "slot_not_available",
    "reoffer_slots",
    "retry_later",
    "booking_complete",
    # Policy gate values added in policy-acceptance change
    "policy_acceptance_required",
    "policy_escalation_required",
    # multi-service-resolution: conversational suggestion fallback for unknown services
    "service_suggestion_required",
}

# R10: no imperative verb prefix
BANNED_PREFIXES = (
    "ask_",
    "call_",
    "wait_",
    "do_",
    "get_",
    "show_",
    "send_",
    "pregunta",
    "llama",
    "debes",
    "haz",
    "envía",
    "muestra",
    "pedí",
    "confirmá",
    "mostrá",
    "responde",
    "verificá",
    "seleccioná",
)

NEXT_STEPS_PATH = (
    pathlib.Path(__file__).parent.parent.parent.parent / "agent" / "tools" / "next_steps.py"
)


class TestVocabularyCompleteness:
    def test_vocabulary_completeness(self):
        """R9: exactly the 12 expected values importable."""
        from agent.tools.next_steps import NextStep

        assert set(NextStep.__args__) == EXPECTED_NEXT_STEP_VALUES

    def test_next_step_literal_has_15_values(self):
        """NextStep now has 15 values: original 12 + policy (2) + service_suggestion_required (1).

        NOTE: policy_acceptance_required and policy_escalation_required were added in the
        policy-acceptance change (12→14). service_suggestion_required added in
        multi-service-resolution (14→15).
        """
        from agent.tools.next_steps import NextStep

        assert len(NextStep.__args__) == 15


class TestNoImperativeVerbs:
    def test_no_imperative_verbs(self):
        """R10: every value is a descriptive noun/state, not an imperative verb."""
        from agent.tools.next_steps import NextStep

        for value in NextStep.__args__:
            for banned in BANNED_PREFIXES:
                assert not value.startswith(
                    banned
                ), f"NextStep value '{value}' starts with imperative prefix '{banned}'"


class TestInlineComments:
    def test_all_values_have_inline_comments(self):
        """R19: each Literal entry has an inline # comment with ≥10 chars."""
        if not NEXT_STEPS_PATH.exists():
            pytest.skip("next_steps.py not yet created")

        source = NEXT_STEPS_PATH.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))

        # Build mapping: line_number -> comment text (stripped of '#')
        comments_by_line: dict[int, str] = {}
        for tok_type, tok_string, tok_start, _, _ in tokens:
            if tok_type == tokenize.COMMENT:
                lineno = tok_start[0]
                comment_body = tok_string.lstrip("#").strip()
                comments_by_line[lineno] = comment_body

        from agent.tools.next_steps import NextStep

        # For each value find its line in source and confirm an inline comment exists
        for value in NextStep.__args__:
            found = False
            for i, line in enumerate(source.splitlines(), start=1):
                if f'"{value}"' in line or f"'{value}'" in line:
                    if i in comments_by_line and len(comments_by_line[i]) >= 10:
                        found = True
                        break
            assert (
                found
            ), f"NextStep value '{value}' lacks an inline comment with ≥10 chars in next_steps.py"


class TestPayloadContract:
    def test_payload_contract_importable(self):
        """R9: NEXT_STEP_PAYLOAD_CONTRACT importable as a dict."""
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        assert isinstance(NEXT_STEP_PAYLOAD_CONTRACT, dict)

    def test_audience_required_has_variants_and_family(self):
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        assert "variants" in NEXT_STEP_PAYLOAD_CONTRACT["audience_required"]
        assert "family" in NEXT_STEP_PAYLOAD_CONTRACT["audience_required"]

    def test_advance_policy_violated_payload_keys(self):
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        keys = NEXT_STEP_PAYLOAD_CONTRACT["advance_policy_violated"]
        assert "first_valid_date" in keys
        assert "policy_min_days" in keys

    def test_booking_complete_payload_keys(self):
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT

        keys = NEXT_STEP_PAYLOAD_CONTRACT["booking_complete"]
        assert "appointment_id" in keys
        assert "calendar_link" in keys

    def test_no_extra_next_step_keys_in_contract(self):
        """Contract keys must be a subset of known NextStep values."""
        from agent.tools.next_steps import NEXT_STEP_PAYLOAD_CONTRACT, NextStep

        for key in NEXT_STEP_PAYLOAD_CONTRACT:
            assert key in NextStep.__args__, f"Unknown key in contract: {key}"
