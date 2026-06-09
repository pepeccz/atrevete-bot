"""
Tests for REQ-H1: Runner output path is single-source-of-truth from orchestrator argument.

T9a: Writer uses exact output_path, creates no secondary files.
T9b: Writer calls Path(output_path).parent.mkdir(parents=True, exist_ok=True) when
     parent dir does not exist.
T9c: Error-outcome run dict also writes to exact output_path.

These tests validate the pattern/contract that must be documented in the runner skill.
The implementation tested here is a reference implementation of the write_run_json helper.
"""

from __future__ import annotations

import json
from pathlib import Path


def write_run_json(run_dict: dict, output_path: str) -> None:
    """
    Reference implementation of the run JSON writer pattern.

    Contract (REQ-H1):
    - Writes ONLY to output_path (no derived paths).
    - Creates parent directory via mkdir(parents=True, exist_ok=True).
    - Uses json.dumps(run_dict, ensure_ascii=False, default=str) for safe serialization.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run_dict, ensure_ascii=False, default=str), encoding="utf-8")


class TestOutputPathContract:
    """H1-S1: Writer uses exact output_path."""

    def test_file_written_at_exact_path(self, tmp_path: Path) -> None:
        """T9a: File is created at the exact output_path provided."""
        output_path = str(tmp_path / "run_dir" / "my-scenario.json")
        run_dict = {"scenario_id": "my-scenario", "outcome": "booked", "turns": []}

        write_run_json(run_dict, output_path)

        written_file = Path(output_path)
        assert written_file.exists(), f"Expected file at {output_path}"
        parsed = json.loads(written_file.read_text(encoding="utf-8"))
        assert parsed["scenario_id"] == "my-scenario"

    def test_no_secondary_files_created(self, tmp_path: Path) -> None:
        """T9a: No secondary .json files with the scenario_id are created under tmp_path."""
        scenario_id = "my-scenario"
        output_path = str(tmp_path / "runs" / f"{scenario_id}.json")
        run_dict = {"scenario_id": scenario_id, "outcome": "booked", "turns": []}

        write_run_json(run_dict, output_path)

        all_json = list(tmp_path.rglob("*.json"))
        assert len(all_json) == 1, f"Expected 1 JSON file, found {len(all_json)}: {all_json}"
        assert all_json[0] == Path(output_path)

    def test_mkdir_called_for_nonexistent_parent(self, tmp_path: Path) -> None:
        """T9b: mkdir(parents=True, exist_ok=True) is called when parent dir doesn't exist."""
        output_path = str(tmp_path / "deep" / "nested" / "scenario.json")
        run_dict = {"scenario_id": "scenario", "outcome": "booked", "turns": []}

        # Parent dir does NOT exist before call
        assert not Path(output_path).parent.exists()

        write_run_json(run_dict, output_path)

        # Parent dir must now exist
        assert Path(output_path).parent.exists()
        # File must exist at exact path
        assert Path(output_path).exists()

    def test_error_outcome_uses_same_path_contract(self, tmp_path: Path) -> None:
        """T9c: Error-outcome run dict is written to same output_path, no fallback location."""
        output_path = str(tmp_path / "error_run" / "failed-scenario.json")
        run_dict = {
            "scenario_id": "failed-scenario",
            "outcome": "error",
            "error": "Unhandled exception during turn 2",
            "turns": [{"turn_number": 1, "user_message": "Hola", "agent_response": None}],
        }

        write_run_json(run_dict, output_path)

        written_file = Path(output_path)
        assert written_file.exists()
        parsed = json.loads(written_file.read_text(encoding="utf-8"))
        assert parsed["outcome"] == "error"
        assert parsed["scenario_id"] == "failed-scenario"

    def test_content_is_valid_json(self, tmp_path: Path) -> None:
        """T9a supplement: the written file must be parseable JSON."""
        output_path = str(tmp_path / "valid.json")
        run_dict = {
            "scenario_id": "valid",
            "turns": [{"user_message": 'texto con "comillas"', "agent_response": "Hola\nmundo"}],
        }

        write_run_json(run_dict, output_path)

        content = Path(output_path).read_text(encoding="utf-8")
        parsed = json.loads(content)  # Must not raise JSONDecodeError
        assert parsed["turns"][0]["user_message"] == 'texto con "comillas"'
        assert "\n" in parsed["turns"][0]["agent_response"]
