"""Unit tests for langfuse_pull.py CLI (AS6, E3).

Covers:
- Happy path: fetches traces by session_id, writes JSON array to output path
- Each trace object contains required fields: id, name, input, output
- Each observation contains required fields: model, input, output
- Retry on empty traces: retries up to --retries times with backoff
- Exit non-zero when no traces after all retries
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_mock_trace(trace_id: str | None = None) -> MagicMock:
    """Create a mock trace object as returned by LangfuseAPI.trace.list."""
    t = MagicMock()
    t.id = trace_id or str(uuid.uuid4())
    t.name = "conversation_turn"
    t.input = {"messages": [{"role": "user", "content": "Hola"}]}
    t.output = {"response": "Hola, ¿en qué te puedo ayudar?"}
    t.model_dict = lambda: {
        "id": t.id,
        "name": t.name,
        "input": t.input,
        "output": t.output,
    }
    return t


def _make_mock_observation() -> MagicMock:
    """Create a mock observation object as returned by LangfuseAPI.observations.get_many."""
    obs = MagicMock()
    obs.model = "gpt-4o-mini"
    obs.input = {"messages": []}
    obs.output = {"content": "Hola"}
    obs.usage = MagicMock()
    obs.usage.input = 120
    obs.usage.output = 45
    obs.model_dict = lambda: {
        "model": obs.model,
        "input": obs.input,
        "output": obs.output,
        "usage": {"input": obs.usage.input, "output": obs.usage.output},
    }
    return obs


# ---------------------------------------------------------------------------
# AS6 — Happy path: writes valid JSON output
# ---------------------------------------------------------------------------


def test_pull_writes_json_array_to_output_path(tmp_path: Path) -> None:
    """AS6: langfuse_pull writes a JSON array to --out path on success."""
    conv_id = str(uuid.uuid4())
    out_path = tmp_path / "traces.json"

    trace = _make_mock_trace()
    obs = _make_mock_observation()

    mock_traces_response = MagicMock()
    mock_traces_response.data = [trace]

    mock_obs_response = MagicMock()
    mock_obs_response.data = [obs]

    with patch("tests.e2e.harness.langfuse_pull.LangfuseAPI") as MockAPI:
        mock_client = MagicMock()
        mock_client.trace.list.return_value = mock_traces_response
        mock_client.observations.get_many.return_value = mock_obs_response
        MockAPI.return_value = mock_client

        with patch("tests.e2e.harness.langfuse_pull.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_PUBLIC_KEY="pub-key",
                LANGFUSE_SECRET_KEY="sec-key",
                LANGFUSE_BASE_URL="https://cloud.langfuse.com",
            )

            from tests.e2e.harness.langfuse_pull import pull_traces

            result = pull_traces(conv_id=conv_id, out=str(out_path), retries=3)

    assert result == 0, "Expected exit code 0 on success"
    assert out_path.exists(), "Output file should be written"

    data = json.loads(out_path.read_text())
    assert isinstance(data, list), "Output must be a JSON array"
    assert len(data) >= 1, "Output must contain at least one trace"


def test_pull_each_trace_has_required_fields(tmp_path: Path) -> None:
    """AS6: Each trace in the output has id, name, input, output fields."""
    conv_id = str(uuid.uuid4())
    out_path = tmp_path / "traces.json"

    trace = _make_mock_trace()
    obs = _make_mock_observation()

    mock_traces_response = MagicMock()
    mock_traces_response.data = [trace]

    mock_obs_response = MagicMock()
    mock_obs_response.data = [obs]

    with patch("tests.e2e.harness.langfuse_pull.LangfuseAPI") as MockAPI:
        mock_client = MagicMock()
        mock_client.trace.list.return_value = mock_traces_response
        mock_client.observations.get_many.return_value = mock_obs_response
        MockAPI.return_value = mock_client

        with patch("tests.e2e.harness.langfuse_pull.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_PUBLIC_KEY="pub-key",
                LANGFUSE_SECRET_KEY="sec-key",
                LANGFUSE_BASE_URL="https://cloud.langfuse.com",
            )

            from tests.e2e.harness.langfuse_pull import pull_traces

            pull_traces(conv_id=conv_id, out=str(out_path), retries=3)

    data = json.loads(out_path.read_text())
    item = data[0]
    assert "trace" in item, "Each output item must have a 'trace' key"
    for field in ("id", "name", "input", "output"):
        assert field in item["trace"], f"Trace must have field '{field}'"


def test_pull_each_observation_has_required_fields(tmp_path: Path) -> None:
    """AS6: Each observation has model, input, output fields."""
    conv_id = str(uuid.uuid4())
    out_path = tmp_path / "traces.json"

    trace = _make_mock_trace()
    obs = _make_mock_observation()

    mock_traces_response = MagicMock()
    mock_traces_response.data = [trace]

    mock_obs_response = MagicMock()
    mock_obs_response.data = [obs]

    with patch("tests.e2e.harness.langfuse_pull.LangfuseAPI") as MockAPI:
        mock_client = MagicMock()
        mock_client.trace.list.return_value = mock_traces_response
        mock_client.observations.get_many.return_value = mock_obs_response
        MockAPI.return_value = mock_client

        with patch("tests.e2e.harness.langfuse_pull.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_PUBLIC_KEY="pub-key",
                LANGFUSE_SECRET_KEY="sec-key",
                LANGFUSE_BASE_URL="https://cloud.langfuse.com",
            )

            from tests.e2e.harness.langfuse_pull import pull_traces

            pull_traces(conv_id=conv_id, out=str(out_path), retries=3)

    data = json.loads(out_path.read_text())
    item = data[0]
    assert "observations" in item, "Each output item must have 'observations' key"
    assert len(item["observations"]) >= 1
    obs_item = item["observations"][0]
    for field in ("model", "input", "output"):
        assert field in obs_item, f"Observation must have field '{field}'"


# ---------------------------------------------------------------------------
# E3 — Retry on flush delay
# ---------------------------------------------------------------------------


def test_pull_retries_on_empty_traces(tmp_path: Path) -> None:
    """E3: pull_traces retries when Langfuse returns empty traces list."""
    conv_id = str(uuid.uuid4())
    out_path = tmp_path / "traces.json"

    trace = _make_mock_trace()
    obs = _make_mock_observation()

    empty_response = MagicMock()
    empty_response.data = []

    success_response = MagicMock()
    success_response.data = [trace]

    mock_obs_response = MagicMock()
    mock_obs_response.data = [obs]

    call_count = 0

    def list_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return empty_response
        return success_response

    with patch("tests.e2e.harness.langfuse_pull.LangfuseAPI") as MockAPI:
        mock_client = MagicMock()
        mock_client.trace.list.side_effect = list_side_effect
        mock_client.observations.get_many.return_value = mock_obs_response
        MockAPI.return_value = mock_client

        with patch("tests.e2e.harness.langfuse_pull.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_PUBLIC_KEY="pub-key",
                LANGFUSE_SECRET_KEY="sec-key",
                LANGFUSE_BASE_URL="https://cloud.langfuse.com",
            )
            with patch("time.sleep"):  # Don't actually sleep in tests
                from tests.e2e.harness.langfuse_pull import pull_traces

                result = pull_traces(conv_id=conv_id, out=str(out_path), retries=3)

    assert result == 0, "Should succeed after retries"
    assert call_count == 3, f"Should have retried: called {call_count} times"


def test_pull_exits_nonzero_after_all_retries_fail(tmp_path: Path) -> None:
    """E3: pull_traces returns non-zero exit code when no traces found after all retries."""
    conv_id = str(uuid.uuid4())
    out_path = tmp_path / "traces.json"

    empty_response = MagicMock()
    empty_response.data = []

    with patch("tests.e2e.harness.langfuse_pull.LangfuseAPI") as MockAPI:
        mock_client = MagicMock()
        mock_client.trace.list.return_value = empty_response
        MockAPI.return_value = mock_client

        with patch("tests.e2e.harness.langfuse_pull.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_PUBLIC_KEY="pub-key",
                LANGFUSE_SECRET_KEY="sec-key",
                LANGFUSE_BASE_URL="https://cloud.langfuse.com",
            )
            with patch("time.sleep"):
                from tests.e2e.harness.langfuse_pull import pull_traces

                result = pull_traces(conv_id=conv_id, out=str(out_path), retries=3)

    assert result != 0, "Should return non-zero when no traces found after all retries"
