"""Unit tests — deterministic audience-disambiguation gate (no live DB/Redis).

Covers the two code-only fixes for the neutral-haircut bug:

1. Catalog-derived audience-FAMILY index (`_booking_helpers`): a neutral term
   like "corte" maps to the audience-ambiguous family and yields an
   `audience_required` descriptor instead of "No reconozco el servicio: corte".
   The index is derived from the catalog, NOT hard-coded — so any audience
   family without a neutral parent principal inherits the behavior.

2. Availability precondition (`check_availability` / `get_next_available_options`):
   when the services sit in an audience-ambiguous dimension and the `audience`
   parameter is None, the tool rejects with `audience_required` so the agent asks
   first instead of offering slots for a guessed gender.

All tests are pure: the family-index helpers are pure functions, and the tool
tests patch the DB-touching helpers (so they run without DATABASE_URL).

Refs: neutral-haircut bug; R32, R9b.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from agent.tools._booking_helpers import (
    _derive_family_stem,
    availability_requires_audience,
    build_audience_family_index,
    dimension_audience_is_ambiguous,
    match_audience_family,
)

# --- Synthetic catalog principal rows (mirror the real shape) -------------------

_CUT_ROWS = [
    {"name": "Corte de Mujer", "audience": "adult_female", "dimension": "cut"},
    {"name": "Corte de Hombre", "audience": "adult_male", "dimension": "cut"},
    {"name": "Corte de Niña", "audience": "child_female", "dimension": "cut"},
    {"name": "Corte de Niño", "audience": "child_male", "dimension": "cut"},
    {"name": "Corte de Bebé", "audience": None, "dimension": "cut"},
    {"name": "Corte de Flequillo", "audience": None, "dimension": "cut"},
]
# manicure: ambiguous (Manicura=null + Manicura de Hombre=adult_male), shared stem.
_MANICURE_ROWS = [
    {"name": "Manicura", "audience": None, "dimension": "manicure"},
    {"name": "Manicura de Hombre", "audience": "adult_male", "dimension": "manicure"},
]
# color: ambiguous in audience BUT names share no leading token → no synthetic stem.
_COLOR_ROWS = [
    {"name": "Tinte", "audience": "adult_female", "dimension": "color"},
    {"name": "Color para Hombre", "audience": "adult_male", "dimension": "color"},
]
# single-audience dimension → never ambiguous (regression guard).
_SINGLE_ROWS = [
    {"name": "Tratamiento Facial", "audience": None, "dimension": "facial"},
    {"name": "Barro Gold Extra", "audience": None, "dimension": "facial"},
]


# ---------------------------------------------------------------------------
# _derive_family_stem
# ---------------------------------------------------------------------------


def test_derive_stem_shared_leading_token():
    assert _derive_family_stem([r["name"] for r in _CUT_ROWS]) == "corte"


def test_derive_stem_no_shared_token_returns_none():
    assert _derive_family_stem(["Tinte", "Color para Hombre"]) is None


def test_derive_stem_too_short_returns_none():
    # "uña"/"uñas" share leading token "una" (3 chars after accent strip) → too short
    assert _derive_family_stem(["Uña Gel", "Uña Normal"]) is None


def test_derive_stem_empty_name_returns_none():
    assert _derive_family_stem(["", "Corte de Mujer"]) is None


# ---------------------------------------------------------------------------
# build_audience_family_index — catalog-derived, not hard-coded
# ---------------------------------------------------------------------------


def test_index_includes_cut_family():
    index = build_audience_family_index(_CUT_ROWS)
    assert "corte" in index
    assert index["corte"]["dimension"] == "cut"
    assert "Corte de Mujer" in index["corte"]["candidates"]


def test_index_includes_manicure_family_proves_not_hardcoded():
    """A second family (manicure) is indexed identically → behavior is catalog-derived."""
    index = build_audience_family_index(_MANICURE_ROWS)
    assert "manicura" in index
    assert index["manicura"]["dimension"] == "manicure"


def test_index_excludes_color_without_shared_stem():
    """Audience-ambiguous but no shared leading token → no synthetic family stem."""
    index = build_audience_family_index(_COLOR_ROWS)
    assert index == {}


def test_index_excludes_single_audience_dimension():
    index = build_audience_family_index(_SINGLE_ROWS)
    assert index == {}


def test_index_multi_family_catalog():
    index = build_audience_family_index(_CUT_ROWS + _MANICURE_ROWS + _COLOR_ROWS + _SINGLE_ROWS)
    assert set(index) == {"corte", "manicura"}


# ---------------------------------------------------------------------------
# match_audience_family — whole-token match, no false positives
# ---------------------------------------------------------------------------


def test_match_neutral_corte():
    index = build_audience_family_index(_CUT_ROWS)
    assert match_audience_family("corte", index)["dimension"] == "cut"


def test_match_corte_de_pelo_phrase():
    index = build_audience_family_index(_CUT_ROWS)
    assert match_audience_family("corte de pelo", index)["dimension"] == "cut"


def test_match_substring_false_positive_guarded():
    """'cortina' must NOT match stem 'corte' (whole-token match only)."""
    index = build_audience_family_index(_CUT_ROWS)
    assert match_audience_family("cortina", index) is None


def test_match_unrelated_term_returns_none():
    index = build_audience_family_index(_CUT_ROWS)
    assert match_audience_family("manicura", index) is None  # color/manicure not in cut index


# ---------------------------------------------------------------------------
# dimension_audience_is_ambiguous — the availability-guard decision
# ---------------------------------------------------------------------------


def test_dimension_ambiguous_true_for_cut():
    assert dimension_audience_is_ambiguous(_CUT_ROWS) is True


def test_dimension_ambiguous_false_for_single_audience():
    assert dimension_audience_is_ambiguous(_SINGLE_ROWS) is False


# ---------------------------------------------------------------------------
# Resolver-level neutral-token behavior (pure: single mocked catalog fetch)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """Minimal async session stub: returns the seeded catalog rows on execute()."""

    def __init__(self, rows: list):
        self._rows = rows

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._rows)


def _catalog_fetch_rows() -> list:
    """Rows shaped like SELECT id, name, audience, metadata_ for the cut family."""
    rows = []
    for r in _CUT_ROWS:
        rows.append(
            (
                uuid4(),
                r["name"],
                r["audience"],
                {"service_type": "principal", "dimension": r["dimension"]},
            )
        )
    return rows


@pytest.mark.asyncio
async def test_resolver_neutral_corte_yields_audience_required_not_unknown():
    """Neutral 'corte' → audience descriptor, NOT 'No reconozco el servicio: corte'.

    This is the secondary-bug fix: the model doing the right thing (bare 'corte')
    must no longer be rejected.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    session = _FakeSession(_catalog_fetch_rows())
    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        session, ["corte"], audience=None
    )

    assert unknown == [], f"'corte' must not be unknown, got {unknown}"
    assert resolved_ids == [], "Ambiguous term must not commit a UUID"
    assert len(ambiguous) == 1
    desc = ambiguous[0]
    assert desc["axis"] == "audience"
    assert desc["question_hint"] == "audience_required"
    assert desc["service_term"] == "corte"
    assert any("Corte de Mujer" in c for c in desc["candidates"])


@pytest.mark.asyncio
async def test_resolver_unrelated_unknown_term_still_unknown():
    """Regression guard: a genuinely unknown term ('peeling') stays unknown."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    session = _FakeSession(_catalog_fetch_rows())
    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        session, ["peeling"], audience=None
    )

    assert unknown == ["peeling"]
    assert ambiguous == []


# ---------------------------------------------------------------------------
# Availability precondition — check_availability / get_next_available_options
# ---------------------------------------------------------------------------

_SID = str(uuid4())
_STYLIST = str(uuid4())


def _future_date() -> str:
    from datetime import date, timedelta

    return (date.today() + timedelta(days=8)).isoformat()


@pytest.mark.asyncio
async def test_check_availability_rejects_when_audience_ambiguous_and_param_none():
    """Multi-audience dimension + audience=None → audience_required (the bug case)."""
    from agent.tools.check_availability import check_availability

    with (
        patch(
            "agent.tools.check_availability._requires_audience_disambiguation",
            AsyncMock(return_value=True),
        ),
        patch(
            "agent.tools.check_availability._load_lead_time_settings",
            AsyncMock(return_value=(0, 0)),
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            AsyncMock(return_value={UUID(_SID): 40}),
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [_SID],
                "stylist_id": None,
                "date_iso": _future_date(),
                "audience": None,
                "no_preference": True,
            }
        )
    data = json.loads(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "audience_required"


@pytest.mark.asyncio
async def test_check_availability_allows_when_audience_param_set():
    """Explicit audience param → guard not consulted → proceeds to slots.

    REGRESSION GUARD: a customer who stated gender (param set) must NOT be re-asked.
    """
    from datetime import date, timedelta

    from agent.tools.check_availability import check_availability

    guard = AsyncMock(side_effect=AssertionError("guard must not run when audience is set"))
    target = date.today() + timedelta(days=8)
    slot = {
        "full_datetime": f"{target}T10:00:00+02:00",
        "stylist_name": "Ana",
        "adjacent_priority": 1,
    }
    with (
        patch("agent.tools.check_availability._requires_audience_disambiguation", guard),
        patch(
            "agent.tools.check_availability._load_lead_time_settings",
            AsyncMock(return_value=(0, 0)),
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            AsyncMock(return_value={UUID(_SID): 40}),
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            AsyncMock(return_value=[UUID(_STYLIST)]),
        ),
        patch(
            "agent.tools.check_availability._get_stylist_names_map",
            AsyncMock(return_value={UUID(_STYLIST): "Ana"}),
        ),
        patch(
            "agent.tools.check_availability.get_available_slots",
            AsyncMock(return_value=[slot]),
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            AsyncMock(return_value=False),
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [_SID],
                "stylist_id": None,
                "date_iso": _future_date(),
                "audience": "adult_female",
                "no_preference": True,
            }
        )
    data = json.loads(raw)
    assert data["status"] == "ok", f"Expected slots, got {data}"


@pytest.mark.asyncio
async def test_check_availability_allows_non_family_service_with_audience_none():
    """Single-audience / non-family service + audience=None → no false gate.

    REGRESSION GUARD: only audience-ambiguous families gate; everything else flows.
    """
    from datetime import date, timedelta

    from agent.tools.check_availability import check_availability

    target = date.today() + timedelta(days=8)
    slot = {
        "full_datetime": f"{target}T11:00:00+02:00",
        "stylist_name": "Ana",
        "adjacent_priority": 1,
    }
    with (
        patch(
            "agent.tools.check_availability._requires_audience_disambiguation",
            AsyncMock(return_value=False),  # non-family service
        ),
        patch(
            "agent.tools.check_availability._load_lead_time_settings",
            AsyncMock(return_value=(0, 0)),
        ),
        patch(
            "agent.tools.check_availability._get_service_durations",
            AsyncMock(return_value={UUID(_SID): 40}),
        ),
        patch(
            "agent.tools.check_availability._get_active_stylists_for_services",
            AsyncMock(return_value=[UUID(_STYLIST)]),
        ),
        patch(
            "agent.tools.check_availability._get_stylist_names_map",
            AsyncMock(return_value={UUID(_STYLIST): "Ana"}),
        ),
        patch(
            "agent.tools.check_availability.get_available_slots",
            AsyncMock(return_value=[slot]),
        ),
        patch(
            "shared.business_hours_validator.is_date_closed",
            AsyncMock(return_value=False),
        ),
    ):
        raw = await check_availability.ainvoke(
            {
                "service_ids": [_SID],
                "stylist_id": None,
                "date_iso": _future_date(),
                "audience": None,
                "no_preference": True,
            }
        )
    data = json.loads(raw)
    assert data["status"] == "ok", f"Non-family service must not be gated, got {data}"


@pytest.mark.asyncio
async def test_next_available_rejects_when_audience_ambiguous_and_param_none():
    """get_next_available_options mirrors the guard → audience_required."""
    from agent.tools.next_available import get_next_available_options

    with (
        patch(
            "agent.tools.next_available._requires_audience_disambiguation",
            AsyncMock(return_value=True),
        ),
        patch(
            "agent.tools.next_available._load_lead_time_settings",
            AsyncMock(return_value=(0, 0)),
        ),
        patch(
            "agent.tools.next_available._get_service_durations",
            AsyncMock(return_value={UUID(_SID): 40}),
        ),
    ):
        raw = await get_next_available_options.ainvoke(
            {
                "service_ids": [_SID],
                "requested_date_iso": _future_date(),
                "stylist_id": None,
                "audience": None,
            }
        )
    data = json.loads(raw)
    assert data["status"] == "rejected"
    assert data["next_step"] == "audience_required"


# ---------------------------------------------------------------------------
# Source-aware guard C — availability_requires_audience (mocked session)
#
# SAFETY INVARIANT: making guard C source-aware must NOT reopen the cold bug.
#   - cold neutral "corte" is stopped by the update_booking gate BEFORE availability.
#   - cold direct-to-availability with a gendered service + NO backing → still BLOCKS
#     (test_guardc_pinned_gendered_no_source_blocks — the safety test).
#   - only NEW behavior: loyal customer WITH backing + pinned gendered → ALLOWS.
# ---------------------------------------------------------------------------


class _SeqResult:
    def __init__(self, rows: list):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _SeqSession:
    """Async session stub returning canned results in call order."""

    def __init__(self, results: list):
        self._queue = list(results)

    async def execute(self, *_args, **_kwargs):
        return self._queue.pop(0)


def _cut_resolved_female():
    return (
        uuid4(),
        "Corte de Mujer",
        "adult_female",
        {"service_type": "principal", "dimension": "cut"},
    )


# dim, audience 2-tuples as returned by the principal-spread query
_CUT_PRINCIPAL_AUDIENCES = [
    ("cut", "adult_female"),
    ("cut", "adult_male"),
    ("cut", "child_female"),
    ("cut", "child_male"),
    ("cut", None),
    ("cut", None),
]


@pytest.mark.asyncio
async def test_guardc_pinned_gendered_no_source_blocks():
    """SAFETY TEST: pinned gendered + audience=None + NO backing → BLOCK.

    This is the cold direct-to-availability bypass — it MUST stay blocked so the
    source-aware change does not reopen the neutral cold bug.
    """
    session = _SeqSession(
        [_SeqResult([_cut_resolved_female()]), _SeqResult(_CUT_PRINCIPAL_AUDIENCES)]
    )
    blocked = await availability_requires_audience(
        session, [str(uuid4())], customer_memories=None, customer_id=None
    )
    assert blocked is True


@pytest.mark.asyncio
async def test_guardc_pinned_gendered_memory_source_allows():
    """LOYAL soft re-ask fixed: pinned gendered + memory backing → ALLOW."""
    session = _SeqSession(
        [_SeqResult([_cut_resolved_female()]), _SeqResult(_CUT_PRINCIPAL_AUDIENCES)]
    )
    blocked = await availability_requires_audience(
        session,
        [str(uuid4())],
        customer_memories={"typical_services": ["Corte de Mujer"]},
        customer_id=None,
    )
    assert blocked is False


@pytest.mark.asyncio
async def test_guardc_pinned_gendered_prior_appt_source_allows():
    """LOYAL via source (b): pinned gendered + prior appointment → ALLOW."""
    prior_sid = uuid4()
    session = _SeqSession(
        [
            _SeqResult([_cut_resolved_female()]),
            _SeqResult(_CUT_PRINCIPAL_AUDIENCES),
            _SeqResult([([prior_sid],)]),  # appt.service_ids arrays
            _SeqResult([(prior_sid,)]),  # services matching the audience
        ]
    )
    blocked = await availability_requires_audience(
        session, [str(uuid4())], customer_memories=None, customer_id=str(uuid4())
    )
    assert blocked is False


@pytest.mark.asyncio
async def test_guardc_ambiguous_neutral_principal_blocks_regardless_of_source():
    """Genuinely ambiguous (null-audience principal in multi-audience dim) → BLOCK,
    even with memory present — we cannot know which audience."""
    resolved = (uuid4(), "Manicura", None, {"service_type": "principal", "dimension": "manicure"})
    principals = [("manicure", None), ("manicure", "adult_male")]
    session = _SeqSession([_SeqResult([resolved]), _SeqResult(principals)])
    blocked = await availability_requires_audience(
        session,
        [str(uuid4())],
        customer_memories={"typical_services": ["Manicura de Hombre"]},
        customer_id=None,
    )
    assert blocked is True


@pytest.mark.asyncio
async def test_guardc_single_audience_service_allows():
    """Non-family / single-audience service + audience=None → no false gate."""
    resolved = (uuid4(), "Mechas", "adult_female", {"service_type": "principal", "dimension": "hl"})
    principals = [("hl", "adult_female")]
    session = _SeqSession([_SeqResult([resolved]), _SeqResult(principals)])
    blocked = await availability_requires_audience(
        session, [str(uuid4())], customer_memories=None, customer_id=None
    )
    assert blocked is False


# ---------------------------------------------------------------------------
# Flow 4 — neutral family token + EXPLICIT audience resolves to the gendered
# principal instead of re-asking. The neutral-no-audience path is unchanged.
# ---------------------------------------------------------------------------


def test_index_carries_by_audience_map():
    index = build_audience_family_index(_CUT_ROWS)
    by_aud = index["corte"]["by_audience"]
    assert by_aud["adult_male"] == "Corte de Hombre"
    assert by_aud["adult_female"] == "Corte de Mujer"
    assert by_aud["child_male"] == "Corte de Niño"
    assert None not in by_aud  # null-audience principals (Bebé/Flequillo) excluded


def _cut_catalog_with_ids():
    """Catalog fetch rows for the cut family + a name→uuid map for assertions."""
    rows: list = []
    ids: dict[str, str] = {}
    for r in _CUT_ROWS:
        sid = uuid4()
        ids[r["name"]] = str(sid)
        rows.append(
            (sid, r["name"], r["audience"], {"service_type": "principal", "dimension": "cut"})
        )
    return rows, ids


@pytest.mark.asyncio
async def test_resolver_corte_plus_adult_male_resolves_corte_de_hombre():
    """FLOW-4 FIX: 'corte' + audience=adult_male → resolves to Corte de Hombre."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    rows, ids = _cut_catalog_with_ids()
    resolved_ids, unknown, ambiguous, partial = await _resolve_service_ids_strict(
        _FakeSession(rows), ["corte"], audience="adult_male"
    )
    assert ambiguous == [], f"explicit audience must not re-ask, got {ambiguous}"
    assert unknown == []
    assert resolved_ids == [ids["Corte de Hombre"]]


@pytest.mark.asyncio
async def test_resolver_corte_plus_adult_female_resolves_corte_de_mujer():
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    rows, ids = _cut_catalog_with_ids()
    resolved_ids, _u, ambiguous, _p = await _resolve_service_ids_strict(
        _FakeSession(rows), ["corte"], audience="adult_female"
    )
    assert ambiguous == []
    assert resolved_ids == [ids["Corte de Mujer"]]


@pytest.mark.asyncio
async def test_resolver_corte_plus_child_male_resolves_corte_de_nino():
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    rows, ids = _cut_catalog_with_ids()
    resolved_ids, _u, ambiguous, _p = await _resolve_service_ids_strict(
        _FakeSession(rows), ["corte"], audience="child_male"
    )
    assert ambiguous == []
    assert resolved_ids == [ids["Corte de Niño"]]


@pytest.mark.asyncio
async def test_resolver_corte_no_audience_still_audience_required():
    """REGRESSION GUARD: neutral 'corte' with NO audience → still audience_required."""
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    rows, _ids = _cut_catalog_with_ids()
    resolved_ids, unknown, ambiguous, _p = await _resolve_service_ids_strict(
        _FakeSession(rows), ["corte"], audience=None
    )
    assert resolved_ids == []
    assert unknown == []
    assert len(ambiguous) == 1
    assert ambiguous[0]["question_hint"] == "audience_required"


@pytest.mark.asyncio
async def test_resolver_corte_de_dama_with_audience_resolves_adult_female():
    """Explicit synonym 'corte de dama' + audience=adult_female → Corte de Mujer.

    'corte de dama' is not an exact catalog name, so it hits the family fallback;
    with the audience param set (the qualifier→audience mapping the prompt drives)
    it resolves to the adult_female principal.
    """
    from agent.tools._booking_helpers import _resolve_service_ids_strict

    rows, ids = _cut_catalog_with_ids()
    resolved_ids, _u, ambiguous, _p = await _resolve_service_ids_strict(
        _FakeSession(rows), ["corte de dama"], audience="adult_female"
    )
    assert ambiguous == []
    assert resolved_ids == [ids["Corte de Mujer"]]
