"""
Phase 8.1 RED: Per-leaf prompt tests.

Asserts:
- Each of the 9 LLM leaf nodes loads its own .md file from agent/prompts/modes/booking/
- No leaf loads from the monolithic booking.md (modes/booking.md)
- No leaf prompt exceeds 200 words (approximate, split by whitespace)
- booking.md monolith does NOT exist (deleted in 8.2)

Node list (leaf LLM nodes only — await_confirmation is silent no-op):
  ask_service, ask_audience, ask_more_services, ask_stylist,
  ask_slot, ask_name, ask_notes, show_confirmation,
  booking_complete, error_recovery
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_BOOKING_PROMPTS_DIR = _REPO_ROOT / "agent" / "prompts" / "modes" / "booking"
_MONOLITH_PATH = _REPO_ROOT / "agent" / "prompts" / "modes" / "booking.md"

_LEAF_NODES = [
    "ask_service",
    "ask_audience",
    "ask_more_services",
    "ask_stylist",
    "ask_slot",
    "ask_name",
    "ask_notes",
    "show_confirmation",
    "booking_complete",
    "error_recovery",
]


# ---------------------------------------------------------------------------
# 8.1a — Per-node .md files exist in booking/ subdirectory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node_name", _LEAF_NODES)
def test_per_node_prompt_file_exists(node_name: str) -> None:
    """Each leaf node must have its own .md under agent/prompts/modes/booking/."""
    prompt_path = _BOOKING_PROMPTS_DIR / f"{node_name}.md"
    assert prompt_path.exists(), (
        f"Missing per-node prompt: {prompt_path}. "
        f"Each LLM leaf node must have its own .md file."
    )


# ---------------------------------------------------------------------------
# 8.1b — No per-node prompt is empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node_name", _LEAF_NODES)
def test_per_node_prompt_not_empty(node_name: str) -> None:
    """Each leaf prompt must have actual content (> 5 words)."""
    prompt_path = _BOOKING_PROMPTS_DIR / f"{node_name}.md"
    content = prompt_path.read_text(encoding="utf-8").strip()
    word_count = len(content.split())
    assert word_count > 5, (
        f"{node_name}.md has only {word_count} words — must have meaningful content."
    )


# ---------------------------------------------------------------------------
# 8.1c — No per-node prompt exceeds 200 words
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node_name", _LEAF_NODES)
def test_per_node_prompt_under_200_words(node_name: str) -> None:
    """Each leaf prompt must be terse — max 200 words (approximate token count)."""
    prompt_path = _BOOKING_PROMPTS_DIR / f"{node_name}.md"
    content = prompt_path.read_text(encoding="utf-8")
    word_count = len(content.split())
    assert word_count <= 200, (
        f"{node_name}.md has {word_count} words — must be ≤200 words. "
        f"Per-leaf prompts must be terse and single-purpose."
    )


# ---------------------------------------------------------------------------
# 8.1d — Monolithic booking.md does NOT exist (deleted)
# ---------------------------------------------------------------------------


def test_monolithic_booking_md_deleted() -> None:
    """The monolithic booking.md must be deleted — per-leaf prompts replace it."""
    assert not _MONOLITH_PATH.exists(), (
        f"Monolithic booking.md still exists at {_MONOLITH_PATH}. "
        f"It must be deleted — subgraph uses per-leaf prompts in booking/ subdirectory."
    )


# ---------------------------------------------------------------------------
# 8.1e — loader.py does NOT map BOOKING to modes/booking.md
# ---------------------------------------------------------------------------


def test_loader_does_not_reference_monolithic_booking() -> None:
    """loader.py must not map BOOKING mode to the deleted booking.md."""
    loader_path = _REPO_ROOT / "agent" / "prompts" / "loader.py"
    content = loader_path.read_text(encoding="utf-8")
    # The _MODE_OVERLAY_FILES dict must not have BOOKING → modes/booking.md
    assert '"BOOKING": "modes/booking.md"' not in content, (
        "loader.py still maps BOOKING to modes/booking.md — remove this entry. "
        "The booking subgraph loads per-leaf prompts directly via leaf_llm._load_prompt()."
    )


# ---------------------------------------------------------------------------
# 8.1f — leaf_llm._load_prompt resolves to booking/ subdirectory (not monolith)
# ---------------------------------------------------------------------------


def test_leaf_llm_prompt_dir_points_to_booking_subdir() -> None:
    """leaf_llm._PROMPTS_DIR must point to agent/prompts/modes/booking/ subdirectory."""
    from agent.booking.nodes.leaf_llm import _PROMPTS_DIR

    assert _PROMPTS_DIR.name == "booking", (
        f"_PROMPTS_DIR is '{_PROMPTS_DIR}' — expected it to end in 'booking'. "
        f"leaf_llm must load from agent/prompts/modes/booking/, not a monolithic file."
    )
    assert _PROMPTS_DIR.is_dir(), (
        f"_PROMPTS_DIR '{_PROMPTS_DIR}' is not a directory."
    )
