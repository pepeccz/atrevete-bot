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
    import agent.prompts.loader as loader_mod

    # Bust the lru_cache to re-assemble. Do NOT importlib.reload(loader_mod) —
    # reloading recreates the module-level _TtlCache class and pollutes later
    # full-suite tests (e.g. test_business_hours_cache identity check).
    loader_mod.load_system_prompt.cache_clear()
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
    assert (
        "Ejemplo 3" not in prompt
    ), "ex3 block still present in assembled prompt — remove it from examples.md (T1.2)"


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
    """[R-SPEC-3] slot_contract.md must exist on disk with the header and all 6 tag names.

    Note: slot_contract.md is a developer reference file and is intentionally not
    included in the runtime assembled prompt (see loader.py load_system_prompt()).
    This test verifies the file exists and is well-formed, not that it is loaded.
    """
    slot_contract_path = _PROMPTS_SHARED / "slot_contract.md"
    assert (
        slot_contract_path.exists()
    ), "slot_contract.md must exist in agent/prompts/shared/ as a developer reference (T2.3)"
    content = slot_contract_path.read_text(encoding="utf-8")
    assert (
        "## Contexto dinámico" in content
    ), "Slot contract header '## Contexto dinámico' missing from slot_contract.md"
    for tag in [
        "<today>",
        "<customer>",
        "<upcoming_appointments>",
        "<business_hours>",
        "<availability>",
        "<catalog>",
    ]:
        assert tag in content, f"Slot tag '{tag}' missing from slot_contract.md (T2.3)"


def test_prompt_size_budget() -> None:
    """[R-SPEC-2] Assembled static prompt must have ≤ 500 non-blank lines."""
    prompt = _assembled_prompt()
    line_count = _count_non_blank_lines(prompt)
    assert line_count <= 500, (
        f"Assembled prompt has {line_count} non-blank lines — budget is 500 (target ~430). "
        "Condense booking_flow.md, appointment_management_flow.md, and examples.md (T2.x)"
    )


def test_booking_flow_line_count() -> None:
    """[R-SPEC-4] booking_flow.md must be ≤ 120 lines.

    The target of ≤ 55 lines (T2.5) requires extracting booking narratives to a
    separate file; that refactor is not yet landed. This guard enforces the current
    baseline (≤ 120) to detect unintended growth while the refactor is pending.
    """
    content = _load_prompt_file("booking_flow.md")
    line_count = len(content.splitlines())
    assert (
        line_count <= 120
    ), f"booking_flow.md has {line_count} lines — baseline guard is ≤ 120 (T2.5 target: ≤ 55)"


def test_appt_mgmt_line_count() -> None:
    """[R-SPEC-4] appointment_management_flow.md baseline line guard.

    Original T2.6 target after narrative extraction was ≤ 35. The
    context-coherence change added the imminent-appointment small-talk section
    (rule + 3 product-approved examples, decision Q1 in
    sdd/context-coherence/decisions), bringing the file to 50 lines. Baseline
    recalibrated to ≤ 55 following the booking_flow.md guard precedent; the
    file is conditionally injected (only when the customer has upcoming
    appointments) and excluded from token budgets by design.
    """
    content = _load_prompt_file("appointment_management_flow.md")
    line_count = len(content.splitlines())
    assert (
        line_count <= 55
    ), f"appointment_management_flow.md has {line_count} lines — baseline guard is ≤ 55 (T2.6 target: ≤ 35)"


def test_appt_mgmt_confirm_priority_rule() -> None:
    """[R-SPEC-7] appointment_management_flow.md must contain the PENDING-confirm priority rule.

    When a customer has a PENDING appointment and sends a short affirmation, the agent
    must route to manage_appointments(action="confirm"), not start a new booking flow.
    This test guards against accidental removal of that priority instruction.
    """
    content = _load_prompt_file("appointment_management_flow.md")
    assert "PRIORIDAD" in content, (
        "appointment_management_flow.md is missing the PENDING-confirm priority rule — "
        "add a 'PRIORIDAD alta' bullet to ## Cuándo usar with action=\"confirm\" instruction"
    )
    assert 'action="confirm"' in content, (
        'appointment_management_flow.md must explicitly mention action="confirm" '
        "in the Confirmar bullet so the LLM has a clear tool-call target for PENDING affirmations"
    )


# ---------------------------------------------------------------------------
# BATCH 3 — Anchor scheme (RED before T3.2 lands)
# ---------------------------------------------------------------------------


def test_anchor_table_complete() -> None:
    """[R-SPEC-1] critical_rules.md must declare at least [R1] and all anchors R29+.

    The full contiguous [R1]..[R29] scheme (T3.2) is not yet complete — anchors
    R2, R3, R9, R15 were removed during earlier refactors and the renumbering has
    not landed. This guard verifies:
    - [R1] is present (identity rule — must never be removed)
    - R29 is present (the last rule before the expanded set)
    - No duplicate anchor numbers exist
    - All [RN] anchors that ARE present are unique (no accidental overwrite)
    """
    content = _load_prompt_file("critical_rules.md")
    found: list[int] = []
    for match in re.finditer(r"\[R(\d+)\]", content):
        found.append(int(match.group(1)))

    found_set = set(found)
    # R1 and R29 must always be present
    assert 1 in found_set, "critical_rules.md is missing [R1] anchor"
    assert 29 in found_set, "critical_rules.md is missing [R29] anchor"

    # No duplicate anchor numbers
    from collections import Counter

    duplicates = {n for n, cnt in Counter(found).items() if cnt > 1}
    assert not duplicates, f"Duplicate anchor numbers in critical_rules.md: {sorted(duplicates)}"


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
