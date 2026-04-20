"""
B.2.1 [RED] — Assert that add_more_answered is removed from UpdateBookingSchema.

After Phase B.2, the update_booking tool no longer has an add_more_answered parameter.
The pre-loop negation resolver (patch_pipeline.py) becomes the SOLE writer for
add_more_asked.

Expected failure on master: 'add_more_answered' IS in UpdateBookingSchema.model_fields.
"""

from __future__ import annotations


class TestNegationSoleWriter:
    """Assert that add_more_answered is removed from update_booking (B.2.1)."""

    def test_update_booking_schema_has_no_add_more_answered(self):
        """UpdateBookingSchema must NOT have add_more_answered field.

        RED on master: field exists at booking_data_tools.py:108.
        GREEN after B.2.5: field deleted.
        """
        from agent.tools.booking_data_tools import UpdateBookingSchema

        assert "add_more_answered" not in UpdateBookingSchema.model_fields, (
            "'add_more_answered' is still in UpdateBookingSchema.model_fields. "
            "This field must be removed in Phase B.2 — the pre-loop negation resolver "
            "is the sole writer for add_more_asked."
        )

    def test_update_booking_function_has_no_add_more_answered(self):
        """update_booking() function must NOT have an add_more_answered parameter.

        Verified via source file inspection (LangChain @tool wraps into StructuredTool;
        use file read to check the raw source).
        """
        from pathlib import Path
        source_path = Path(__file__).parent.parent.parent.parent / "agent" / "tools" / "booking_data_tools.py"
        source = source_path.read_text(encoding="utf-8")
        assert "add_more_answered" not in source, (
            "'add_more_answered' still appears in booking_data_tools.py. "
            "This parameter must be removed in Phase B.2."
        )

    def test_no_add_more_answered_in_tool_source(self):
        """Source code of booking_data_tools.py must have zero occurrences of add_more_answered.

        RED on master: multiple occurrences (lines 108, 203, 279, 517-519).
        GREEN after B.2.5: zero occurrences.
        """
        import inspect as _inspect

        import agent.tools.booking_data_tools as bdt

        source = _inspect.getsource(bdt)
        assert "add_more_answered" not in source, (
            "booking_data_tools.py still contains 'add_more_answered'. "
            "All references must be removed in Phase B.2."
        )
