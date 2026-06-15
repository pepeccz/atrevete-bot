"""
Unit tests for Google OAuth2 / credential factory components.

Coverage:
- shared/encryption.py  — encrypt_token / decrypt_token round-trip and error cases
- agent/services/gcal_credential_factory.py — OAuth2 path, service-account fallback, neither
- agent/services/google_oauth_service.py — generate_auth_url / not-configured guard

Test naming: test_<scenario_description>
Async tests use pytest-asyncio with asyncio_mode=auto (project-wide setting).

Note on module mocking:
    google_auth_oauthlib and googleapiclient are not installed in the local/test Python
    (they live in the Docker container). We stub them via sys.modules before the first import
    so the module-level code in google_oauth_service.py and gcal_credential_factory.py can
    be loaded. This is the same pattern used throughout the test suite for Docker-only deps.
"""

from __future__ import annotations

# Docker-only packages (google_auth_oauthlib, googleapiclient) are stubbed in
# tests/conftest.py BEFORE this module is imported. No need to re-stub here.
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.services.gcal_credential_factory as _factory_module  # noqa: E402
import agent.services.google_oauth_service as _oauth_module  # noqa: E402
import shared.encryption as _encryption_module  # noqa: E402
from agent.services.gcal_credential_factory import (  # noqa: E402
    GCalAuthError,
    get_google_credentials,
)
from agent.services.google_oauth_service import GoogleOAuthService  # noqa: E402
from shared.encryption import decrypt_token, encrypt_token  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    admin_jwt_secret: str = "test-secret-min-16ch",
    client_id: str = "",
    client_secret: str = "",
    sa_json: str = "",
    redirect_uri: str = "http://localhost/callback",
) -> MagicMock:
    """Build a MagicMock that looks like a Settings instance."""
    s = MagicMock()
    s.ADMIN_JWT_SECRET = admin_jwt_secret
    s.GOOGLE_OAUTH_CLIENT_ID = client_id
    s.GOOGLE_OAUTH_CLIENT_SECRET = client_secret
    s.GOOGLE_SERVICE_ACCOUNT_JSON = sa_json
    s.GOOGLE_OAUTH_REDIRECT_URI = redirect_uri
    s.google_oauth_configured = bool(client_id and client_secret)
    return s


# ===========================================================================
# Encryption utilities
# ===========================================================================


class TestEncryptionRoundtrip:
    """encrypt_token / decrypt_token must be inverse operations."""

    def test_encrypt_decrypt_roundtrip(self):
        """encrypt_token(x) → decrypt_token(result) == x."""
        fake_settings = _make_settings()

        with patch.object(_encryption_module, "get_settings", return_value=fake_settings):
            plaintext = "ya29.access-token-value"
            ciphertext = encrypt_token(plaintext)
            assert decrypt_token(ciphertext) == plaintext

    def test_encrypt_produces_different_ciphertext_each_time(self):
        """
        Fernet uses a random IV so the same plaintext produces a different
        ciphertext on every call (yet both must decrypt to the same value).
        """
        fake_settings = _make_settings()

        with patch.object(_encryption_module, "get_settings", return_value=fake_settings):
            plaintext = "same-plaintext-value"
            ct1 = encrypt_token(plaintext)
            ct2 = encrypt_token(plaintext)

            # Different ciphertexts
            assert ct1 != ct2

            # Both decrypt to the same value
            assert decrypt_token(ct1) == plaintext
            assert decrypt_token(ct2) == plaintext

    def test_decrypt_garbage_raises(self):
        """decrypt_token with a corrupted payload must raise InvalidToken."""
        from cryptography.fernet import InvalidToken

        fake_settings = _make_settings()

        with patch.object(_encryption_module, "get_settings", return_value=fake_settings):
            with pytest.raises(InvalidToken):
                decrypt_token("this-is-not-valid-fernet-ciphertext")

    def test_decrypt_wrong_key_raises(self):
        """A token encrypted with key A cannot be decrypted with key B."""
        from cryptography.fernet import InvalidToken

        settings_a = _make_settings(admin_jwt_secret="secret-key-A-min16")
        settings_b = _make_settings(admin_jwt_secret="secret-key-B-min16")

        with patch.object(_encryption_module, "get_settings", return_value=settings_a):
            ciphertext = encrypt_token("my-token")

        with patch.object(_encryption_module, "get_settings", return_value=settings_b):
            with pytest.raises(InvalidToken):
                decrypt_token(ciphertext)


# ===========================================================================
# Credential factory
# ===========================================================================


class TestCredentialFactory:
    """Tests for agent/services/gcal_credential_factory.get_google_credentials()."""

    async def test_factory_uses_oauth2_when_configured(self):
        """
        When OAuth2 is configured in settings and the OAuth service returns valid
        credentials, the factory must return them and NOT touch the service account.
        """
        fake_settings = _make_settings(
            client_id="client-id",
            client_secret="client-secret",
        )
        fake_settings.google_oauth_configured = True

        mock_creds = MagicMock(name="OAuth2Credentials")
        mock_oauth_service = AsyncMock()
        mock_oauth_service.get_credentials = AsyncMock(return_value=mock_creds)

        with (
            patch.object(_factory_module, "get_settings", return_value=fake_settings),
            patch.object(_factory_module, "_oauth_service", mock_oauth_service),
        ):
            mock_session = AsyncMock()
            result = await get_google_credentials(session=mock_session)

        assert result is mock_creds
        mock_oauth_service.get_credentials.assert_awaited_once_with(mock_session)

    async def test_factory_falls_back_to_service_account_when_no_oauth(
        self, tmp_path
    ):
        """
        When OAuth2 is not configured (no CLIENT_ID/SECRET), the factory must fall
        back to the service account file and return SA credentials.
        """
        sa_file = tmp_path / "service-account.json"
        # The factory checks os.path.exists(), so the file must exist.
        sa_file.write_text('{"type": "service_account"}')

        fake_settings = _make_settings(sa_json=str(sa_file))
        fake_settings.google_oauth_configured = False

        mock_sa_creds = MagicMock(name="ServiceAccountCredentials")

        with (
            patch.object(_factory_module, "get_settings", return_value=fake_settings),
            patch.object(
                _factory_module.service_account.Credentials,
                "from_service_account_file",
                return_value=mock_sa_creds,
            ),
        ):
            result = await get_google_credentials(session=None)

        assert result is mock_sa_creds

    async def test_factory_falls_back_to_service_account_on_oauth_failure(
        self, tmp_path
    ):
        """
        If OAuth2 is configured but get_credentials raises GoogleOAuthError,
        the factory must fall back to the service account file.
        """
        from agent.services.google_oauth_service import GoogleOAuthNotConfiguredError

        sa_file = tmp_path / "service-account.json"
        sa_file.write_text('{"type": "service_account"}')

        fake_settings = _make_settings(
            client_id="client-id",
            client_secret="client-secret",
            sa_json=str(sa_file),
        )
        fake_settings.google_oauth_configured = True

        mock_sa_creds = MagicMock(name="ServiceAccountCredentials")
        mock_oauth_service = AsyncMock()
        # Simulate no active row in DB
        mock_oauth_service.get_credentials = AsyncMock(
            side_effect=GoogleOAuthNotConfiguredError("no active row")
        )

        with (
            patch.object(_factory_module, "get_settings", return_value=fake_settings),
            patch.object(_factory_module, "_oauth_service", mock_oauth_service),
            patch.object(
                _factory_module.service_account.Credentials,
                "from_service_account_file",
                return_value=mock_sa_creds,
            ),
        ):
            mock_session = AsyncMock()
            result = await get_google_credentials(session=mock_session)

        assert result is mock_sa_creds

    async def test_factory_raises_when_neither_configured(self):
        """
        When neither OAuth2 nor a service account file is available,
        the factory must raise GCalAuthError.
        """
        fake_settings = _make_settings(sa_json="")
        fake_settings.google_oauth_configured = False

        with (
            patch.object(_factory_module, "get_settings", return_value=fake_settings),
            patch.object(_factory_module.os.path, "exists", return_value=False),
        ):
            with pytest.raises(GCalAuthError):
                await get_google_credentials(session=None)

    async def test_factory_skips_oauth2_when_session_is_none(self, tmp_path):
        """
        When session=None is passed, the factory must skip the OAuth2 attempt
        entirely (even if OAuth2 is configured) and go straight to service account.
        """
        sa_file = tmp_path / "service-account.json"
        sa_file.write_text('{"type": "service_account"}')

        fake_settings = _make_settings(
            client_id="client-id",
            client_secret="client-secret",
            sa_json=str(sa_file),
        )
        fake_settings.google_oauth_configured = True

        mock_sa_creds = MagicMock(name="ServiceAccountCredentials")
        mock_oauth_service = AsyncMock()

        with (
            patch.object(_factory_module, "get_settings", return_value=fake_settings),
            patch.object(_factory_module, "_oauth_service", mock_oauth_service),
            patch.object(
                _factory_module.service_account.Credentials,
                "from_service_account_file",
                return_value=mock_sa_creds,
            ),
        ):
            result = await get_google_credentials(session=None)

        # Must NOT have called OAuth service at all
        mock_oauth_service.get_credentials.assert_not_awaited()
        assert result is mock_sa_creds


# ===========================================================================
# GoogleOAuthService — generate_auth_url
# ===========================================================================


class TestGoogleOAuthServiceGenerateAuthUrl:
    """Tests for GoogleOAuthService.generate_auth_url()."""

    def test_generate_auth_url_returns_url_and_state(self):
        """
        generate_auth_url() must return a tuple of (url_str, state_str) where
        url_str starts with 'https://accounts.google.com' and state_str is
        a non-empty URL-safe string.
        """
        fake_settings = _make_settings(
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?...",
            "unused-state",
        )

        mock_flow.code_verifier = "fake-code-verifier"

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module.Flow, "from_client_config", return_value=mock_flow),
        ):
            service = GoogleOAuthService()
            url, state, _code_verifier = service.generate_auth_url()

        assert isinstance(url, str)
        assert url.startswith("https://accounts.google.com")
        assert isinstance(state, str)
        assert len(state) > 0

    def test_generate_auth_url_accepts_custom_state(self):
        """When a state is passed explicitly, generate_auth_url uses it as-is."""
        fake_settings = _make_settings(
            client_id="test-client-id",
            client_secret="test-client-secret",
        )

        custom_state = "my-csrf-token-abc123"

        mock_flow = MagicMock()
        mock_flow.code_verifier = "fake-code-verifier"
        mock_flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?state=" + custom_state,
            custom_state,
        )

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module.Flow, "from_client_config", return_value=mock_flow),
        ):
            service = GoogleOAuthService()
            url, returned_state, _code_verifier = service.generate_auth_url(state=custom_state)

        assert returned_state == custom_state
        # Check that our custom state was passed to authorization_url
        _, kwargs = mock_flow.authorization_url.call_args
        assert kwargs.get("state") == custom_state

    def test_generate_auth_url_raises_when_not_configured(self):
        """
        When CLIENT_ID and CLIENT_SECRET are empty, Flow.from_client_config raises.
        The test verifies generate_auth_url propagates that exception.
        """
        fake_settings = _make_settings(client_id="", client_secret="")

        # Simulate Flow.from_client_config raising ValueError for missing client_id
        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(
                _oauth_module.Flow,
                "from_client_config",
                side_effect=ValueError("client_id is required"),
            ),
        ):
            service = GoogleOAuthService()
            with pytest.raises(Exception):
                service.generate_auth_url()
