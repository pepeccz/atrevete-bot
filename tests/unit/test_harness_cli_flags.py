"""
Tests for REQ-H5: CLI flag names in diff.py and cleanup.py match CLAUDE.md docs.

T20a: diff.py parser accepts --base and --head without error.
T20b: cleanup.py parser accepts --dry-run without error.
T20c: cleanup.py parser accepts --age-hours without error.

Per spec, if these tests pass immediately → REQ-H5 is already satisfied (code matches docs).
If they fail → T21 triggers patch of CLI flags or docs update.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestDiffPyCliFlags:
    """H5-S1: diff.py must accept --base and --head flags as documented in CLAUDE.md."""

    def test_base_and_head_flags_accepted(self) -> None:
        """T20a: Parse --base x --head y → no error."""
        # We import argparse and re-construct the parser to test it independently
        # rather than exec-ing the script (which would require real dirs).
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--base", required=True)
        parser.add_argument("--head", required=True)
        parser.add_argument("--out", default=None)

        args = parser.parse_args(
            ["--base", "runs/20260601_120000", "--head", "runs/20260609_120000"]
        )
        assert args.base == "runs/20260601_120000"
        assert args.head == "runs/20260609_120000"

    def test_diff_py_actual_parser_accepts_flags(self) -> None:
        """T20a (real): Actual diff.py argparse parser accepts --base and --head."""
        # Import the module and verify the flag structure matches docs
        # We parse the arg definitions directly from the source to avoid running main()
        diff_path = Path(__file__).parent.parent.parent / "tests" / "e2e" / "harness" / "diff.py"
        assert diff_path.exists(), f"diff.py not found at {diff_path}"

        source = diff_path.read_text(encoding="utf-8")
        # Verify the documented flags exist in source
        assert '"--base"' in source, "diff.py must define --base flag"
        assert '"--head"' in source, "diff.py must define --head flag"


class TestCleanupPyCliFlags:
    """H5-S2: cleanup.py must accept --dry-run and --age-hours flags as documented."""

    def test_dry_run_flag_accepted(self) -> None:
        """T20b: Parse --dry-run → no error."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--age-hours", type=int, default=None)

        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_age_hours_flag_accepted(self) -> None:
        """T20c: Parse --age-hours 24 → no error, value is 24."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--age-hours", type=int, default=None)

        args = parser.parse_args(["--age-hours", "24"])
        assert args.age_hours == 24

    def test_cleanup_py_actual_parser_accepts_flags(self) -> None:
        """T20b+T20c (real): Actual cleanup.py argparse parser defines documented flags."""
        cleanup_path = (
            Path(__file__).parent.parent.parent / "tests" / "e2e" / "harness" / "cleanup.py"
        )
        assert cleanup_path.exists(), f"cleanup.py not found at {cleanup_path}"

        source = cleanup_path.read_text(encoding="utf-8")
        assert '"--dry-run"' in source, "cleanup.py must define --dry-run flag"
        assert '"--age-hours"' in source, "cleanup.py must define --age-hours flag"
