"""Regression tests for the tool-schema-fix change."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from pydantic import BaseModel

from agent.tools.info_tools import list_stylists
from agent.utils.service_disambiguation import _build_clarification


def test_list_stylists_has_explicit_schema():
    schema = list_stylists.args_schema

    assert schema is not None, "list_stylists must have an explicit args_schema"
    assert issubclass(schema, BaseModel), "args_schema must be a Pydantic BaseModel"
    assert "category" in schema.model_fields, "schema must have 'category' field"


def test_clarification_option_includes_metadata():
    svc = MagicMock()
    svc.name = "Cortar"
    svc.id = uuid4()
    svc.duration_minutes = 40
    svc.description = "Corte capilar completo"
    svc.category = MagicMock(value="HAIRDRESSING")
    svc.metadata_ = {
        "family": "haircut",
        "audience": "adult_female",
        "combo_recommendations": ["Secado"],
    }

    payload = _build_clarification("audience", [svc])
    option = payload.options[0]

    assert option["category"] == "HAIRDRESSING"
    assert option["family"] == "haircut"
    assert option["combo_recommendations"] == ["Secado"]
    assert option["description"] == "Corte capilar completo"


def test_clarification_resolution_preserves_service_category():
    svc = MagicMock()
    svc.name = "Cortar"
    svc.id = uuid4()
    svc.duration_minutes = 40
    svc.description = "Corte capilar completo"
    svc.category = MagicMock(value="HAIRDRESSING")
    svc.metadata_ = {
        "family": "haircut",
        "audience": "adult_female",
        "combo_recommendations": ["Secado"],
    }

    clarification = _build_clarification("audience", [svc])
    matched_option = clarification.options[0]
    mode_context = {}
    confirmed_context = {
        **mode_context,
        "service_name": matched_option.get("service_name", ""),
        "service_id": matched_option.get("service_id"),
        "service_duration_minutes": matched_option.get("duration_minutes"),
        "service_category": matched_option.get("category", mode_context.get("service_category", "")),
        "service_family": matched_option.get("family", mode_context.get("service_family")),
        "pending_recommendations": matched_option.get("combo_recommendations")
        or mode_context.get("pending_recommendations")
        or [],
    }

    assert confirmed_context["service_category"] == "HAIRDRESSING"
    assert confirmed_context["pending_recommendations"] == ["Secado"]
