"""
Tests for _build_customer_memory_context and memory injection in loader.py (TASK-6).

Verifies:
- _build_customer_memory_context formats all sections correctly per spec AC-8.6
- Stylist line threshold (visit_count >= 2)
- no_preference_stylist trumps preferred_stylist
- Services: single vs multiple, empty
- Day/time formatting (mañana/tarde)
- Notes included/omitted
- Last visit date inline with service
- _build_simple_dynamic_context injects memories when present
- _build_simple_dynamic_context skips when None/absent
"""

import pytest

from agent.prompts.loader import _build_customer_memory_context, _build_simple_dynamic_context


# ──────────────────────────────────────────────────────────────────────
# Pure function: _build_customer_memory_context
# ──────────────────────────────────────────────────────────────────────


def test_memory_context_header_present():
    """Any non-empty dict → section starts with '## Historial del cliente'."""
    result = _build_customer_memory_context({"visit_count": 1})
    assert "## Historial del cliente" in result


def test_memory_context_visit_count():
    """visit_count=5 → 'Visitas anteriores: 5' in output."""
    result = _build_customer_memory_context({"visit_count": 5})
    assert "Visitas anteriores: 5" in result


def test_memory_context_stylist_above_threshold():
    """visit_count=2, preferred_stylist_name='Pilar' → 'Estilista habitual: Pilar' present."""
    result = _build_customer_memory_context(
        {"visit_count": 2, "preferred_stylist_name": "Pilar"}
    )
    assert "Estilista habitual: Pilar" in result


def test_memory_context_stylist_below_threshold():
    """visit_count=1, preferred_stylist_name='Maria' → 'Estilista habitual' NOT present."""
    result = _build_customer_memory_context(
        {"visit_count": 1, "preferred_stylist_name": "Maria"}
    )
    assert "Estilista habitual" not in result


def test_memory_context_no_preference():
    """no_preference_stylist=True, visit_count=3 → 'Sin preferencia' present, stylist NOT."""
    result = _build_customer_memory_context(
        {"visit_count": 3, "no_preference_stylist": True, "preferred_stylist_name": "Pilar"}
    )
    assert "Sin preferencia de estilista" in result
    assert "Estilista habitual" not in result


def test_memory_context_services_single():
    """typical_services=['CORTE'] → 'Último servicio: CORTE' present, 'Servicios frecuentes' NOT."""
    result = _build_customer_memory_context({"visit_count": 1, "typical_services": ["CORTE"]})
    assert "Último servicio: CORTE" in result
    assert "Servicios frecuentes" not in result


def test_memory_context_services_multiple():
    """typical_services=['A','B','C'] → both 'Último servicio' and 'Servicios frecuentes' present."""
    result = _build_customer_memory_context(
        {"visit_count": 3, "typical_services": ["CORTE LARGO", "TINTE", "PEINADO"]}
    )
    assert "Último servicio: CORTE LARGO" in result
    assert "Servicios frecuentes:" in result
    assert "TINTE" in result


def test_memory_context_no_services():
    """typical_services=[] → neither 'Último servicio' nor 'Servicios frecuentes' present."""
    result = _build_customer_memory_context({"visit_count": 1, "typical_services": []})
    assert "Último servicio" not in result
    assert "Servicios frecuentes" not in result


def test_memory_context_day_morning():
    """typical_day_of_week='sábado', typical_time_of_day='morning' → 'sábado por la mañana'."""
    result = _build_customer_memory_context(
        {"visit_count": 1, "typical_day_of_week": "sábado", "typical_time_of_day": "morning"}
    )
    assert "sábado por la mañana" in result


def test_memory_context_day_afternoon():
    """typical_time_of_day='afternoon' → 'por la tarde' present."""
    result = _build_customer_memory_context(
        {"visit_count": 1, "typical_day_of_week": "viernes", "typical_time_of_day": "afternoon"}
    )
    assert "por la tarde" in result


def test_memory_context_notes_included():
    """notes='alergia al amoniaco' → present in output."""
    result = _build_customer_memory_context(
        {"visit_count": 1, "notes": "alergia al amoniaco"}
    )
    assert "alergia al amoniaco" in result
    assert "Notas:" in result


def test_memory_context_notes_empty_omitted():
    """notes=None → 'Notas' NOT present."""
    result = _build_customer_memory_context({"visit_count": 1, "notes": None})
    assert "Notas" not in result


def test_memory_context_last_visit_date_inline():
    """last_visit_date='2026-03-15' → appears after service name in parens."""
    result = _build_customer_memory_context(
        {
            "visit_count": 1,
            "typical_services": ["CORTE LARGO"],
            "last_visit_date": "2026-03-15",
        }
    )
    assert "(2026-03-15)" in result
    assert "CORTE LARGO (2026-03-15)" in result


# ──────────────────────────────────────────────────────────────────────
# Integration with _build_simple_dynamic_context
# ──────────────────────────────────────────────────────────────────────


def test_build_simple_dynamic_context_injects_memories():
    """State with customer_memories dict → output contains '## Historial del cliente'."""
    state = {
        "customer_phone": "+34612345678",
        "customer_memories": {
            "visit_count": 3,
            "preferred_stylist_name": "Pilar",
            "typical_services": ["CORTE LARGO"],
        },
    }
    result = _build_simple_dynamic_context(state)
    assert "## Historial del cliente" in result
    assert "Visitas anteriores: 3" in result


def test_build_simple_dynamic_context_skips_none_memories():
    """State with customer_memories=None → output does NOT contain '## Historial del cliente'."""
    state = {
        "customer_phone": "+34612345678",
        "customer_memories": None,
    }
    result = _build_simple_dynamic_context(state)
    assert "## Historial del cliente" not in result


def test_build_simple_dynamic_context_skips_missing_memories():
    """State without customer_memories key → output does NOT contain '## Historial del cliente'."""
    state = {
        "customer_phone": "+34612345678",
    }
    result = _build_simple_dynamic_context(state)
    assert "## Historial del cliente" not in result
