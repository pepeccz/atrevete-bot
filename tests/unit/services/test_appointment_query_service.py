"""
Tests for agent/services/appointment_query_service.py — public API cleanup.

Coverage:
- T5.1 RED: public names exist (get_customer_by_phone, get_upcoming_appointments, get_service_names)
- T5.1 AST: manage_appointments_tool.py imports only public names (no leading underscore)
- T5.1 IMPORT: underscore variants are NOT importable as public API
"""

import ast
import importlib
import inspect

import pytest


# =============================================================================
# T5.1 — Public API contract
# =============================================================================


class TestPublicApiExists:
    """Public function names must be importable from appointment_query_service."""

    def test_get_customer_by_phone_is_importable(self):
        """get_customer_by_phone must exist as a public name."""
        from agent.services import appointment_query_service

        assert hasattr(appointment_query_service, "get_customer_by_phone"), (
            "appointment_query_service must expose 'get_customer_by_phone' as a public name"
        )

    def test_get_appointments_by_customer_id_is_importable(self):
        """get_appointments_by_customer_id must exist as a public name (renamed from _get_upcoming_appointments)."""
        from agent.services import appointment_query_service

        # The internal helper _get_upcoming_appointments(customer_id) was renamed to
        # get_appointments_by_customer_id to avoid collision with the public
        # get_upcoming_appointments(customer_phone) wrapper.
        assert hasattr(appointment_query_service, "get_appointments_by_customer_id"), (
            "appointment_query_service must expose 'get_appointments_by_customer_id' as a public name "
            "(renamed from _get_upcoming_appointments)"
        )

    def test_get_service_names_is_importable(self):
        """get_service_names must exist as a public name."""
        from agent.services import appointment_query_service

        assert hasattr(appointment_query_service, "get_service_names"), (
            "appointment_query_service must expose 'get_service_names' as a public name"
        )

    def test_underscore_variants_do_not_exist(self):
        """The old underscore-prefixed private names must not exist after cleanup."""
        from agent.services import appointment_query_service

        # After rename, the old underscore names should no longer be present
        assert not hasattr(appointment_query_service, "_get_customer_by_phone"), (
            "_get_customer_by_phone must be renamed to get_customer_by_phone"
        )
        assert not hasattr(appointment_query_service, "_get_upcoming_appointments"), (
            "_get_upcoming_appointments must be renamed to get_appointments_by_customer_id"
        )
        assert not hasattr(appointment_query_service, "_get_service_names"), (
            "_get_service_names must be renamed to get_service_names"
        )

    def test_public_names_are_coroutine_functions(self):
        """The renamed public helpers must be async functions."""
        import asyncio

        from agent.services import appointment_query_service

        assert asyncio.iscoroutinefunction(appointment_query_service.get_customer_by_phone), (
            "get_customer_by_phone must be an async function"
        )
        assert asyncio.iscoroutinefunction(
            appointment_query_service.get_appointments_by_customer_id
        ), "get_appointments_by_customer_id must be an async function"
        assert asyncio.iscoroutinefunction(appointment_query_service.get_service_names), (
            "get_service_names must be an async function"
        )


# =============================================================================
# T5.1 AST — manage_appointments_tool.py imports only public names
# =============================================================================


class TestManageAppointmentsToolImportsNoUnderscore:
    """manage_appointments_tool.py must not import underscore-prefixed names from appointment_query_service."""

    def test_no_underscore_imports_from_appointment_query_service(self):
        """AST walk: no leading-underscore name imported from appointment_query_service."""
        import ast

        tool_path = (
            "/home/pepe/Projects/Clientes/atrevete-bot"
            "/agent/tools/manage_appointments_tool.py"
        )
        with open(tool_path) as f:
            tree = ast.parse(f.read())

        underscore_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "appointment_query_service" in module:
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            underscore_imports.append(alias.name)
            # Also check inline imports inside function bodies (ImportFrom inside function)
            # ast.walk already handles this recursively

        assert underscore_imports == [], (
            f"manage_appointments_tool.py imports underscore names from "
            f"appointment_query_service: {underscore_imports}. "
            f"Rename to public API (no leading underscore)."
        )
