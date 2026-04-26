"""T7.b RED — no hardcoded advance policy in catalog_builder.py.

R-IDs: R14
"""
from __future__ import annotations

from pathlib import Path

CATALOG_BUILDER_PATH = (
    Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "catalog_builder.py"
)


def test_no_hardcoded_advance_policy() -> None:
    source = CATALOG_BUILDER_PATH.read_text(encoding="utf-8")
    assert "Anticipación mínima: 3 días" not in source, (
        "catalog_builder.py contains hardcoded advance policy text. "
        "Inject value from DB (SettingsService) instead."
    )
    # Broader check: the literal "3 días" should not appear as a standalone booking policy
    assert '"3 días"' not in source and "'3 días'" not in source, (
        "catalog_builder.py contains the literal string '3 días'. "
        "Policy values must come from the database."
    )
