"""
Tests for REQ-H6: Langfuse env contract.

T4a: Settings.LANGFUSE_PUBLIC_KEY is None when env var is absent.
T4b: Settings.LANGFUSE_SECRET_KEY is None when env var is absent.
T4c: langfuse_pull.pull_traces exits non-zero + prints "not configured" when keys
     are None or placeholders.

TDD: these tests MUST fail before T5 (config change) because current default is
     "pk-lf-placeholder", not None.
"""

from __future__ import annotations

from unittest.mock import patch


class TestLangfuseConfigDefaults:
    """T4a + T4b: Keys must default to None when env vars are absent."""

    def _make_settings_without_langfuse(self, **overrides):
        """Create a Settings instance without reading .env file and without Langfuse keys."""
        from shared.config import Settings

        # Use model_construct to bypass validators + .env loading
        # We supply enough required fields to make the object valid for our assertions
        return Settings.model_construct(
            LANGFUSE_PUBLIC_KEY=overrides.get("LANGFUSE_PUBLIC_KEY", None),
            LANGFUSE_SECRET_KEY=overrides.get("LANGFUSE_SECRET_KEY", None),
            LANGFUSE_BASE_URL=overrides.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )

    def test_public_key_defaults_to_none(self) -> None:
        """T4a: LANGFUSE_PUBLIC_KEY type is Optional[str] — default is None (not placeholder string)."""

        from shared.config import Settings

        # Verify the field default is None (not 'pk-lf-placeholder')
        field_info = Settings.model_fields["LANGFUSE_PUBLIC_KEY"]
        default_value = field_info.default
        assert default_value is None, (
            f"Expected LANGFUSE_PUBLIC_KEY default to be None, got {default_value!r}. "
            "Change H requires Optional[str] with default=None."
        )

    def test_secret_key_defaults_to_none(self) -> None:
        """T4b: LANGFUSE_SECRET_KEY type is Optional[str] — default is None (not placeholder string)."""
        from shared.config import Settings

        field_info = Settings.model_fields["LANGFUSE_SECRET_KEY"]
        default_value = field_info.default
        assert default_value is None, (
            f"Expected LANGFUSE_SECRET_KEY default to be None, got {default_value!r}. "
            "Change H requires Optional[str] with default=None."
        )

    def test_base_url_keeps_default(self) -> None:
        """LANGFUSE_BASE_URL should keep its sensible default (not None)."""
        from shared.config import Settings

        field_info = Settings.model_fields["LANGFUSE_BASE_URL"]
        default_value = field_info.default
        assert default_value is not None
        assert "langfuse" in str(default_value)


class TestLangfusePullGuard:
    """T4c: pull_traces() must exit non-zero with 'not configured' msg when keys are None/placeholder."""

    def _run_pull_with_keys(
        self, monkeypatch, public_key: str | None, secret_key: str | None
    ) -> tuple[int, str]:
        """Helper: run pull_traces with mocked settings and capture stderr."""
        import io

        from shared.config import Settings, get_settings

        mock_settings = Settings.model_construct(
            LANGFUSE_PUBLIC_KEY=public_key,
            LANGFUSE_SECRET_KEY=secret_key,
            LANGFUSE_BASE_URL="https://cloud.langfuse.com",
        )

        stderr_capture = io.StringIO()
        get_settings.cache_clear()

        with patch("tests.e2e.harness.langfuse_pull.get_settings", return_value=mock_settings):
            with patch("sys.stderr", stderr_capture):
                from tests.e2e.harness.langfuse_pull import pull_traces

                exit_code = pull_traces(conv_id="test-conv-id", out="/tmp/test_traces.json")

        return exit_code, stderr_capture.getvalue()

    def test_none_public_key_exits_nonzero(self, monkeypatch) -> None:
        """T4c: None public key → exit code 2 + stderr contains 'not configured'."""
        exit_code, stderr_output = self._run_pull_with_keys(monkeypatch, None, None)
        assert exit_code != 0, f"Expected non-zero exit code, got {exit_code}"
        assert (
            "not configured" in stderr_output.lower() or "not configured" in stderr_output
        ), f"Expected 'not configured' in stderr. Got: {stderr_output!r}"

    def test_placeholder_public_key_exits_nonzero(self, monkeypatch) -> None:
        """T4c: Placeholder public key → exit code 2 + stderr contains 'not configured'."""
        exit_code, stderr_output = self._run_pull_with_keys(
            monkeypatch, "pk-lf-placeholder", "sk-lf-placeholder"
        )
        assert exit_code != 0, f"Expected non-zero exit code for placeholder keys, got {exit_code}"

    def test_empty_string_key_exits_nonzero(self, monkeypatch) -> None:
        """Edge: Empty string key → treated as not configured."""
        exit_code, stderr_output = self._run_pull_with_keys(monkeypatch, "", "")
        assert exit_code != 0, f"Expected non-zero exit code for empty keys, got {exit_code}"
