"""Tests for tools_contract.md — schema arg name sync (AS6, F4).

F4: tools_contract.md must use date_iso (not date:) for check_availability
    and requested_date_iso (not from_date:) for get_next_available_options.
"""

from __future__ import annotations

from pathlib import Path

_CONTRACT_PATH = (
    Path(__file__).parent.parent.parent
    / "agent" / "prompts" / "shared" / "tools_contract.md"
)


def _read_contract() -> str:
    return _CONTRACT_PATH.read_text(encoding="utf-8")


class TestCheckAvailabilityArgNames:
    """check_availability must use date_iso, not date:."""

    def test_date_iso_present_in_contract(self) -> None:
        """date_iso must appear in tools_contract.md."""
        content = _read_contract()
        assert "date_iso" in content, (
            "tools_contract.md must reference date_iso for check_availability arg"
        )

    def test_old_date_colon_absent_in_arg_spec_line(self) -> None:
        """'date:' must not appear as an arg spec line for check_availability.

        Prose references to 'date' are OK; only the contract arg-name line is in scope.
        The pattern '`date`' or 'date:' inside an args description block must not exist.
        """
        content = _read_contract()
        # The old arg spec format was "date (YYYY-MM-DD)" — check for that pattern
        # A bare `date:` at start of an arg line is the violation
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match arg-spec lines like "- Args requeridos: `service_ids` (UUIDs), `date` (YYYY-MM-DD)"
            # or lines starting with "date:" as an arg name
            if "`date`" in stripped and "date_iso" not in stripped:
                # Allow if it's within a fenced code block (illustrative)
                # Violation is in normative prose
                raise AssertionError(
                    f"Line {i+1}: found `date` without date_iso in tools_contract.md: {line!r}"
                )


class TestGetNextAvailableArgNames:
    """get_next_available_options must use requested_date_iso, not from_date:."""

    def test_requested_date_iso_present_in_contract(self) -> None:
        """requested_date_iso must appear in tools_contract.md."""
        content = _read_contract()
        assert "requested_date_iso" in content, (
            "tools_contract.md must reference requested_date_iso for get_next_available_options"
        )

    def test_from_date_absent_as_arg_spec(self) -> None:
        """from_date must not appear as a normative arg name in tools_contract.md.

        It may still appear in prose context (e.g., 'from_date=payload.from_date')
        describing payload routing — only the normative arg-name spec is in scope.
        """
        content = _read_contract()
        # The normative arg spec lists "from_date" as a required arg name
        # Pattern: "Args requeridos: ... from_date" or "- `from_date`" as an arg
        lines = content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Check for the old normative arg spec line that listed from_date
            if "Args requeridos:" in stripped and "from_date" in stripped:
                raise AssertionError(
                    f"Line {i+1}: 'from_date' found in Args requeridos spec — "
                    f"must be requested_date_iso: {line!r}"
                )


class TestActualToolSchemaAlignment:
    """Cross-check: actual tool Pydantic schemas must match contract names."""

    def test_check_availability_uses_date_iso(self) -> None:
        """check_availability tool schema must have date_iso field."""
        from agent.tools.check_availability import check_availability

        fields = check_availability.args_schema.model_fields
        assert "date_iso" in fields, (
            f"check_availability schema missing date_iso. Fields: {list(fields)}"
        )

    def test_get_next_available_uses_requested_date_iso(self) -> None:
        """get_next_available_options tool schema must have requested_date_iso field."""
        from agent.tools.next_available import get_next_available_options

        fields = get_next_available_options.args_schema.model_fields
        assert "requested_date_iso" in fields, (
            f"get_next_available_options schema missing requested_date_iso. Fields: {list(fields)}"
        )
