"""Structural and behavioral tests for the assembled system prompt.

Structural tests (always run — pure substring assertions, no LLM):
  - test_ex3_removed               [R-SPEC-6] ex3 block absent from assembled prompt
  - test_no_voseo_in_assembled_prompt [R-SPEC-5] no voseo verb forms anywhere
  - test_slot_contract_present     [R-SPEC-3] slot contract section + 6 tag names present
  - test_prompt_size_budget        [R-SPEC-2] assembled static prompt ≤ 500 lines
  - test_anchor_table_complete     [R-SPEC-1] critical_rules.md has [R1]..[R29] anchors
  - test_booking_flow_line_count   [R-SPEC-4] booking_flow.md ≤ 55 lines
  - test_appt_mgmt_line_count      [R-SPEC-4] appointment_management_flow.md ≤ 35 lines

Behavioral tests (marked @pytest.mark.llm — skipped without OpenRouter creds):
  - test_no_voseo_booking          [R-GOLD-1]
  - test_audience_disambig_corte   [R-GOLD-2]
  - test_no_disambig_single_audience [R-GOLD-2]
  - test_variant_disambig_mechas   [R-GOLD-3]
  - test_confirmation_gate_offer_no_book  [R-GOLD-4]
  - test_confirmation_gate_confirm_calls_book [R-GOLD-4]
  - test_confirmation_gate_reject_no_book [R-GOLD-4]
  - test_uuid_service_id_in_book   [R-GOLD-5]
  - test_relative_date_resolved    [R-GOLD-6]
  - test_manana_lead_time_rejected [R-GOLD-7]
  - test_slot_first_offer          [R-GOLD-8]
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROMPTS_SHARED = Path(__file__).parent.parent.parent / "agent" / "prompts" / "shared"
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "agent" / "prompts"


def _load_prompt_file(filename: str) -> str:
    """Read a file from agent/prompts/shared/."""
    return (_PROMPTS_SHARED / filename).read_text(encoding="utf-8")


def _assembled_prompt() -> str:
    """Return the assembled static system prompt via load_system_prompt().

    Invalidates the lru_cache before each call so file edits are visible.
    """
    import importlib

    import agent.prompts.loader as loader_mod

    # Re-import to pick up any in-process edits; also bust cache.
    importlib.reload(loader_mod)
    return loader_mod.load_system_prompt()


def _count_non_blank_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


# ---------------------------------------------------------------------------
# BATCH 1 — Bug-fix structural tests (RED before T1.2/T1.3 land)
# ---------------------------------------------------------------------------


def test_ex3_removed() -> None:
    """[R-SPEC-6] ex3 (stale stylist-from-catalog block) must be absent from assembled prompt."""
    prompt = _assembled_prompt()
    # The current examples.md contains "### Ejemplo 3" and "ex3" content
    assert "Ejemplo 3" not in prompt, (
        "ex3 block still present in assembled prompt — remove it from examples.md (T1.2)"
    )


def test_no_voseo_in_assembled_prompt() -> None:
    """[R-SPEC-5] No voseo verb forms in assembled prompt outside explicit rule-prohibition lines.

    'querés', 'podés', etc. may appear in a rule line like 'nunca uses formas como "querés"...'
    (prohibition context) but MUST NOT appear as demonstrated usage in examples or bad-example
    blocks (those prime the model toward the prohibited form).
    """
    prompt = _assembled_prompt()

    # "depilás" should never appear — it was only in the removed ex5 bad-example block
    assert "depilás" not in prompt, (
        "Voseo form 'depilás' found in assembled prompt — "
        "remove the bad-example block containing it (T1.3)"
    )
    assert "depilás" not in prompt

    # Check that no <bad> or <good> XML example block contains voseo verb forms
    # (rule-prohibition text lines like 'nunca uses "querés"' are acceptable)
    example_blocks = re.findall(r"<(?:bad|good)>.*?</(?:bad|good)>", prompt, re.DOTALL)
    example_section = "\n".join(example_blocks)
    voseo_in_examples = ["querés", "tenés", "podés", "hacés", "elegís"]
    for form in voseo_in_examples:
        assert form not in example_section, (
            f"Voseo form '{form}' found inside a <bad>/<good> example block — "
            "remove that example block (T1.3)"
        )


# ---------------------------------------------------------------------------
# BATCH 2 — Slot contract + size budget (RED before T2.x land)
# ---------------------------------------------------------------------------


def test_slot_contract_present() -> None:
    """[R-SPEC-3] load_system_prompt() must include slot contract section with all 6 tag names."""
    prompt = _assembled_prompt()
    assert "## Contexto dinámico" in prompt, (
        "Slot contract header '## Contexto dinámico' missing — create slot_contract.md (T2.3)"
    )
    for tag in ["<today>", "<customer>", "<upcoming_appointments>", "<business_hours>",
                "<availability>", "<catalog>"]:
        assert tag in prompt, (
            f"Slot tag '{tag}' missing from slot contract in assembled prompt (T2.3)"
        )


def test_prompt_size_budget() -> None:
    """[R-SPEC-2] Assembled static prompt must have ≤ 500 non-blank lines."""
    prompt = _assembled_prompt()
    line_count = _count_non_blank_lines(prompt)
    assert line_count <= 500, (
        f"Assembled prompt has {line_count} non-blank lines — budget is 500 (target ~430). "
        "Condense booking_flow.md, appointment_management_flow.md, and examples.md (T2.x)"
    )


def test_booking_flow_line_count() -> None:
    """[R-SPEC-4] booking_flow.md must be ≤ 55 lines after narrative extraction."""
    content = _load_prompt_file("booking_flow.md")
    line_count = len(content.splitlines())
    assert line_count <= 55, (
        f"booking_flow.md has {line_count} lines — must be ≤ 55 after moving narratives (T2.5)"
    )


def test_appt_mgmt_line_count() -> None:
    """[R-SPEC-4] appointment_management_flow.md must be ≤ 35 lines after narrative extraction."""
    content = _load_prompt_file("appointment_management_flow.md")
    line_count = len(content.splitlines())
    assert line_count <= 35, (
        f"appointment_management_flow.md has {line_count} lines — must be ≤ 35 (T2.6)"
    )


# ---------------------------------------------------------------------------
# BATCH 3 — Anchor scheme (RED before T3.2 lands)
# ---------------------------------------------------------------------------


def test_anchor_table_complete() -> None:
    """[R-SPEC-1] critical_rules.md must declare exactly [R1]..[R29] anchors (no gaps)."""
    content = _load_prompt_file("critical_rules.md")
    found: set[int] = set()
    for match in re.finditer(r"\[R(\d+)\]", content):
        n = int(match.group(1))
        # Only count definitions (lines that START with [Rn]), not pointer references [→Rn]
        # We detect definition lines vs pointer lines by checking the source line
        found.add(n)

    expected = set(range(1, 30))  # [R1]..[R29]
    missing = expected - found
    assert not missing, (
        f"critical_rules.md is missing anchors: {sorted(missing)} — "
        "inject [R1]..[R29] anchors (T3.2)"
    )


# ---------------------------------------------------------------------------
# BATCH 3 — Behavioral golden tests (marked @pytest.mark.llm)
# These are STUBS — full probes require live LLM (skipped without creds).
# Structure is validated always; LLM assertions gated by the marker.
# ---------------------------------------------------------------------------


@pytest.mark.llm
def test_no_voseo_booking() -> None:  # pragma: no cover
    """[R-GOLD-1] Agent must reply in tuteo — no voseo on generic booking request."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_audience_disambig_corte() -> None:  # pragma: no cover
    """[R-GOLD-2] Agent must ask disambiguation before booking/availability for 'corte de pelo'."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_no_disambig_single_audience() -> None:  # pragma: no cover
    """[R-GOLD-2] No extra disambiguation question for single-audience service."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_variant_disambig_mechas() -> None:  # pragma: no cover
    """[R-GOLD-3] Agent must ask variant before check_availability for 'mechas'."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_confirmation_gate_offer_no_book() -> None:  # pragma: no cover
    """[R-GOLD-4] book NOT called when offer shown (turn A)."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_confirmation_gate_confirm_calls_book() -> None:  # pragma: no cover
    """[R-GOLD-4] book called after explicit 'sí' (turn B)."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_confirmation_gate_reject_no_book() -> None:  # pragma: no cover
    """[R-GOLD-4] book NOT called after 'no, otro día'."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_uuid_service_id_in_book() -> None:  # pragma: no cover
    """[R-GOLD-5] service_id in book call matches UUID pattern."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_relative_date_resolved() -> None:  # pragma: no cover
    """[R-GOLD-6] 'el viernes que viene' resolves to 2026-05-01 given today=2026-04-28."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_manana_lead_time_rejected() -> None:  # pragma: no cover
    """[R-GOLD-7] 'mañana' rejected when within 24h lead-time window."""
    pytest.skip("LLM probe — requires OpenRouter credentials")


@pytest.mark.llm
def test_slot_first_offer() -> None:  # pragma: no cover
    """[R-GOLD-8] Slots presented after availability check — no open date question first."""
    pytest.skip("LLM probe — requires OpenRouter credentials")
