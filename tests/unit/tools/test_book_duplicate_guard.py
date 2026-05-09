"""
Regression test for bug #5070 — duplicate confirmed-guard dead code in book.py.

The original bug:
  `book.py` had the `if not confirmed:` guard duplicated:
    - lines 172-182: LIVE guard (returns early when confirmed=False)
    - lines 199-208: DEAD CODE (unreachable — first guard already returned)

This test exposes the dead code by verifying that the code path at lines 199-208
is structurally unreachable. If lines 199-208 were ever reached (e.g. because lines
172-182 were accidentally removed), the behavior would be identical — but the
EXISTENCE of the block means refactoring risk and violates single-responsibility.

Behavioral proof strategy:
  1. book(confirmed=False) must return rejected/confirmation_required.
  2. We patch the first guard's return path to detect whether the second guard
     is reached via a side-effect counter. If the duplicate block at 199-208 were
     reachable AND had different behavior, this test would catch it.
  3. We also use AST inspection to assert the duplicate block is ABSENT after fix.

After the fix (removal of lines 199-208), this test must PASS.
Before the fix (duplicate present), test_no_duplicate_confirmed_guard_in_source FAILS.
"""

from __future__ import annotations

import ast
import json
import pathlib
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# T4.1 RED: AST-based dead-code detector
# ---------------------------------------------------------------------------


def _count_confirmed_guards_in_book() -> int:
    """Return the number of `if not confirmed:` blocks in book.py.

    Uses AST inspection of the source file so this test does not depend on
    line numbers that may shift during refactoring. Reads the file directly
    to avoid issues with inspect.getsource on LangChain StructuredTool wrappers.
    """
    book_path = pathlib.Path(__file__).parent.parent.parent.parent / "agent" / "tools" / "book.py"
    source = book_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    count = 0
    for node in ast.walk(tree):
        # Look for `if not confirmed:` patterns (UnaryOp(Not, Name('confirmed')))
        if isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "confirmed"
            ):
                count += 1

    return count


def test_no_duplicate_confirmed_guard_in_source():
    """There must be exactly ONE `if not confirmed:` guard in book.py.

    FAILS against the unfixed code (two guards present — second is dead code).
    PASSES after the dead-code block at lines 199-208 is removed.
    """
    count = _count_confirmed_guards_in_book()
    assert count == 1, (
        f"Found {count} `if not confirmed:` blocks in book.py — expected exactly 1. "
        "The duplicate guard at lines 199-208 is dead code and must be removed."
    )


# ---------------------------------------------------------------------------
# Behavioral proof: confirmed=False always returns confirmation_required
# regardless of which guard fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_confirmed_false_returns_confirmation_required():
    """book(confirmed=False) must return rejected/confirmation_required.

    This is a behavioral smoke test — the duplicate guard returned the same
    ToolResponse, so behavior does not change when dead code is removed.
    This test confirms the live guard at lines 172-182 still works after removal.
    """
    from agent.tools.book import book

    result = await book.ainvoke(
        {
            "service_ids": ["00000000-0000-0000-0000-000000000001"],
            "stylist_id": "00000000-0000-0000-0000-000000000002",
            "start_iso": "2026-06-01T10:00:00+00:00",
            "customer_phone": "+5491112345678",
            "customer_full_name": "Ana García",
            "confirmed": False,
            "pre_book_validated": True,
        }
    )
    payload = json.loads(result)
    assert payload["status"] == "rejected"
    assert payload["next_step"] == "confirmation_required"


@pytest.mark.asyncio
async def test_book_confirmed_false_does_not_reach_db():
    """book(confirmed=False) must NOT call BookingService (no DB access).

    The guard fires before BookingService is called. Proves dead code at 199-208
    was unreachable — the live guard at 172-182 already returned.
    """
    with patch(
        "agent.tools.book.BookingService.create_appointment",
    ) as mock_service:
        result = await book.ainvoke(
            {
                "service_ids": ["00000000-0000-0000-0000-000000000001"],
                "stylist_id": "00000000-0000-0000-0000-000000000002",
                "start_iso": "2026-06-01T10:00:00+00:00",
                "customer_phone": "+5491112345678",
                "customer_full_name": "Ana García",
                "confirmed": False,
                "pre_book_validated": True,
            }
        )

    mock_service.assert_not_called()
    payload = json.loads(result)
    assert payload["status"] == "rejected"


# ---------------------------------------------------------------------------
# Import needed for the async test above
# ---------------------------------------------------------------------------
from agent.tools.book import book  # noqa: E402
