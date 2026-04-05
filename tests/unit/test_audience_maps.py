"""
Unit tests for shared/audience_maps.py — REQ-4: Unified Audience Maps.

Verifies:
- AUDIENCE_HINT_MAP is importable from shared.audience_maps
- No local _AUDIENCE_HINT_MAP definitions remain in agent/ files
- All expected entries are present (superset of all previously-local maps)
"""

from __future__ import annotations

import ast
import os

from shared.audience_maps import AUDIENCE_HINT_MAP, canonicalize_audience


# =============================================================================
# T-42: Architecture guards
# =============================================================================


class TestAudienceMapsArchitectureGuards:
    """T-42: Verify the audience maps module has the correct public API."""

    def test_no_audience_keywords_importable(self):
        """T-42: AUDIENCE_KEYWORDS must NOT be importable from shared.audience_maps.

        The old AUDIENCE_KEYWORDS dict was replaced by AUDIENCE_HINT_MAP.
        Any import attempt must raise ImportError or AttributeError.
        """
        import importlib

        module = importlib.import_module("shared.audience_maps")
        assert not hasattr(module, "AUDIENCE_KEYWORDS"), (
            "AUDIENCE_KEYWORDS found in shared.audience_maps — "
            "this was replaced by AUDIENCE_HINT_MAP in the architecture refactor"
        )

    def test_audience_hint_map_exists(self):
        """T-42: AUDIENCE_HINT_MAP must be importable from shared.audience_maps."""
        from shared.audience_maps import AUDIENCE_HINT_MAP as _ahm  # noqa: F401

        assert _ahm is not None

    def test_canonicalize_audience_exists(self):
        """T-42: canonicalize_audience must be importable from shared.audience_maps."""
        from shared.audience_maps import canonicalize_audience as _ca  # noqa: F401

        assert callable(_ca)


# =============================================================================
# Import test
# =============================================================================


class TestAudienceMapsImport:
    """Verify shared.audience_maps exports the expected symbols."""

    def test_audience_hint_map_is_dict(self):
        assert isinstance(AUDIENCE_HINT_MAP, dict)

    def test_audience_hint_map_has_adult_male_entries(self):
        """All expected adult_male tokens present."""
        for token in ("caballero", "hombre", "adulto", "senor"):
            assert (
                AUDIENCE_HINT_MAP.get(token) == "adult_male"
            ), f"Missing token '{token}' → 'adult_male' in AUDIENCE_HINT_MAP"

    def test_audience_hint_map_has_adult_female_entries(self):
        """All expected adult_female tokens present."""
        for token in ("dama", "mujer", "adulta", "senora"):
            assert (
                AUDIENCE_HINT_MAP.get(token) == "adult_female"
            ), f"Missing token '{token}' → 'adult_female' in AUDIENCE_HINT_MAP"

    def test_audience_hint_map_has_child_entries(self):
        """Child male and female tokens present."""
        assert AUDIENCE_HINT_MAP.get("nino") == "child_male"
        assert AUDIENCE_HINT_MAP.get("nina") == "child_female"
        assert AUDIENCE_HINT_MAP.get("nene") == "child_male"
        assert AUDIENCE_HINT_MAP.get("nena") == "child_female"

    def test_audience_hint_map_has_baby_entry(self):
        assert AUDIENCE_HINT_MAP.get("bebe") == "baby"

    def test_audience_hint_map_superset_of_greeting_mode(self):
        """Superset: must include all tokens that were in greeting_mode.py local map."""
        greeting_tokens = {
            "caballero",
            "hombre",
            "senor",
            "adulto",
            "dama",
            "mujer",
            "senora",
            "adulta",
            "nina",
            "nena",
            "hija",
            "nino",
            "nene",
            "hijo",
        }
        for token in greeting_tokens:
            assert (
                token in AUDIENCE_HINT_MAP
            ), f"Token '{token}' from greeting_mode not found in shared AUDIENCE_HINT_MAP"

    def test_audience_hint_map_superset_of_tool_extractors(self):
        """Superset: must include all tokens that were in tool_extractors.py local map."""
        extractor_tokens = {
            "caballero",
            "hombre",
            "adulto",
            "senor",
            "chico",
            "dama",
            "mujer",
            "adulta",
            "senora",
            "chica",
            "seorita",
            "srita",
            "nino",
            "nene",
            "chiquitin",
            "nina",
            "nena",
            "chiquitina",
            "bebe",
        }
        for token in extractor_tokens:
            assert (
                token in AUDIENCE_HINT_MAP
            ), f"Token '{token}' from tool_extractors not found in shared AUDIENCE_HINT_MAP"

class TestNoDuplicateLocalMaps:
    """REQ-4 Scenario: no local _AUDIENCE_HINT_MAP definitions remain in agent/ files."""

    def _find_local_map_definitions(self, filepath: str, map_name: str) -> list[int]:
        """Return line numbers where `map_name` is assigned as a dict literal in filepath."""
        try:
            with open(filepath) as fh:
                source = fh.read()
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, FileNotFoundError):
            return []

        lines = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == map_name:
                        if isinstance(node.value, ast.Dict):
                            lines.append(node.lineno)
        return lines

    def _agent_root(self) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(here, "..", "..", "agent")

    def test_greeting_mode_has_no_local_audience_hint_map(self):
        filepath = os.path.join(self._agent_root(), "modes", "greeting_mode.py")
        lines = self._find_local_map_definitions(filepath, "_AUDIENCE_HINT_MAP")
        assert lines == [], (
            f"greeting_mode.py still defines _AUDIENCE_HINT_MAP at lines {lines}. "
            "Should import from shared.audience_maps."
        )

    def test_shared_audience_maps_imports_work_from_agent_modes(self):
        """greeting_mode.py must import from shared.audience_maps."""
        for filename in ("greeting_mode.py",):
            filepath = os.path.join(self._agent_root(), "modes", filename)
            with open(filepath) as fh:
                source = fh.read()
            assert (
                "from shared.audience_maps import" in source
            ), f"{filename} does not import from shared.audience_maps"


class TestCanonicalizeAudience:
    """REQ-1: canonicalize_audience() tokenizes compound audience values."""

    def test_compound_slash_returns_first_canonical(self):
        """AC-1.1: 'Dama / Señora' → 'adult_female'."""
        assert canonicalize_audience("Dama / Señora") == "adult_female"

    def test_accented_single_token(self):
        """AC-1.2: 'señora' → 'adult_female'."""
        assert canonicalize_audience("señora") == "adult_female"

    def test_compound_comma_returns_first_match(self):
        """AC-1.3: 'Caballero, Adulto' → 'adult_male'."""
        assert canonicalize_audience("Caballero, Adulto") == "adult_male"

    def test_unknown_value_passthrough(self):
        """AC-1.4: unknown values pass through unchanged."""
        assert canonicalize_audience("unknown_value") == "unknown_value"

    def test_conjunction_y_skipped(self):
        """AC-1.5: 'Dama y Caballero' → 'adult_female' (first match)."""
        assert canonicalize_audience("Dama y Caballero") == "adult_female"

    def test_empty_string_no_error(self):
        assert canonicalize_audience("") == ""

    def test_whitespace_only_no_error(self):
        result = canonicalize_audience("  ")
        assert isinstance(result, str)

    def test_already_canonical_passthrough(self):
        """AC-1.7: 'adult_female' passes through (not in AUDIENCE_HINT_MAP but no match)."""
        assert canonicalize_audience("adult_female") == "adult_female"

    def test_accented_compound_nino_nina(self):
        """'Señora / Niña' → 'adult_female' (first match after accent strip)."""
        assert canonicalize_audience("Señora / Niña") == "adult_female"

    def test_nino_single(self):
        assert canonicalize_audience("Niño") == "child_male"

    def test_bebe_single(self):
        assert canonicalize_audience("Bebé") == "baby"
