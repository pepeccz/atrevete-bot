"""Unit tests for BookingMode._load_service_names family grouping.

Validates that ServiceCatalogEntry.siblings is populated using the
(dimension, service_type='principal') grouping key, not the naive name.split()[0].

Regression coverage for the haircut family bug: 'Cortar' must find its
'Corte Niña/Niño/Caballero' siblings and vice versa.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.booking_mode import BookingMode


def _row(name: str, audience: str | None, metadata: dict | None):
    """Build a mock row returned by session.execute().all() — (name, audience, metadata_)."""
    return (name, audience, metadata)


def _make_mock_session(rows: list[tuple]) -> MagicMock:
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


CUT_PRINCIPAL = {"service_type": "principal", "dimension": "cut", "parent_service_name": None}
CUT_VARIANT = {
    "service_type": "variant",
    "dimension": "cut",
    "parent_service_name": "Corte Caballero",
}


class TestLoadServiceNamesFamilyGrouping:
    """Catalog entries must expose dimension-based audience siblings."""

    @pytest.mark.asyncio
    async def test_cortar_has_full_cut_family_siblings(self):
        rows = [
            _row("Cortar", "adult_female", CUT_PRINCIPAL),
            _row("Corte Niña", "child_female", CUT_PRINCIPAL),
            _row("Corte Niño", "child_male", CUT_PRINCIPAL),
            _row("Corte Caballero", "adult_male", CUT_PRINCIPAL),
        ]
        session = _make_mock_session(rows)

        with patch("database.connection.get_async_session", return_value=session):
            entries = await BookingMode._load_service_names()

        cortar = next(e for e in entries if e.name == "Cortar")
        assert cortar.has_audience_siblings is True
        assert set(cortar.siblings) == {
            "Cortar",
            "Corte Niña",
            "Corte Niño",
            "Corte Caballero",
        }

    @pytest.mark.asyncio
    async def test_corte_caballero_siblings_symmetric_with_cortar(self):
        rows = [
            _row("Cortar", "adult_female", CUT_PRINCIPAL),
            _row("Corte Niña", "child_female", CUT_PRINCIPAL),
            _row("Corte Niño", "child_male", CUT_PRINCIPAL),
            _row("Corte Caballero", "adult_male", CUT_PRINCIPAL),
        ]
        session = _make_mock_session(rows)

        with patch("database.connection.get_async_session", return_value=session):
            entries = await BookingMode._load_service_names()

        corte_caballero = next(e for e in entries if e.name == "Corte Caballero")
        assert "Cortar" in corte_caballero.siblings, (
            f"Symmetric siblings broken: {corte_caballero.siblings!r}"
        )

    @pytest.mark.asyncio
    async def test_variant_has_no_family_siblings(self):
        rows = [
            _row("Corte Caballero", "adult_male", CUT_PRINCIPAL),
            _row("Barba", "adult_male", CUT_VARIANT),
        ]
        session = _make_mock_session(rows)

        with patch("database.connection.get_async_session", return_value=session):
            entries = await BookingMode._load_service_names()

        barba = next(e for e in entries if e.name == "Barba")
        assert barba.siblings == [], f"Variant should have no siblings, got {barba.siblings!r}"
        assert barba.has_audience_siblings is False

    @pytest.mark.asyncio
    async def test_audience_less_service_has_no_siblings(self):
        rows = [
            _row("Cortar", "adult_female", CUT_PRINCIPAL),
            _row("Peinado", None, {"service_type": "principal", "dimension": "hairstyle"}),
        ]
        session = _make_mock_session(rows)

        with patch("database.connection.get_async_session", return_value=session):
            entries = await BookingMode._load_service_names()

        peinado = next(e for e in entries if e.name == "Peinado")
        assert peinado.siblings == []
        assert peinado.has_audience_siblings is False
