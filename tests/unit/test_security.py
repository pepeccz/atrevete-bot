"""Unit tests for shared/security.py — bcrypt helpers.

Covers: NFR-2, SC-HASH-1, SC-HASH-2.

IMPORTANT: This module removes the passlib stub from conftest so the real
passlib[bcrypt] library is used (the stub does not implement .using()).
The conftest stub is only needed for modules that import passlib at the
top-level (like api/routes/admin.py) — shared/security.py is purpose-built
and always requires the real library.
"""

from __future__ import annotations

import sys

# Remove passlib stubs installed by conftest before importing shared.security.
# The conftest installs stubs only when "passlib" not in sys.modules, so if
# we delete the stub entries here and re-import passlib, we get the real thing.
for key in list(sys.modules.keys()):
    if key.startswith("passlib"):
        del sys.modules[key]

# Also remove any cached shared.security import that used the stub.
for key in list(sys.modules.keys()):
    if key == "shared.security":
        del sys.modules[key]

# Now import with real passlib
from shared.security import hash_password, verify_password  # noqa: E402


class TestHashPassword:
    """Tests for hash_password() function."""

    def test_hash_password_returns_string(self):
        """hash_password returns a string."""
        hashed = hash_password("mypassword")
        assert isinstance(hashed, str)

    def test_hash_password_starts_with_bcrypt_prefix(self):
        """hash_password produces a bcrypt hash starting with $2b$ (SC-HASH-1)."""
        hashed = hash_password("mypassword")
        assert hashed.startswith(
            "$2b$"
        ), f"Expected bcrypt hash starting with '$2b$', got: {hashed[:10]!r}"

    def test_hash_password_cost_factor_at_least_12(self):
        """hash_password uses bcrypt cost factor >= 12 (NFR-2, SC-HASH-1)."""
        hashed = hash_password("mypassword")
        # bcrypt hash format: $2b$<cost>$<rest>
        parts = hashed.split("$")
        # parts = ['', '2b', '<cost>', '<salt+hash>']
        assert len(parts) >= 4, f"Unexpected bcrypt hash format: {hashed!r}"
        cost = int(parts[2])
        assert cost >= 12, f"bcrypt cost factor must be >= 12, got {cost}"

    def test_hash_password_different_plain_produces_different_hash(self):
        """Two different passwords produce different hashes."""
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_hash_password_same_plain_produces_different_hash_each_time(self):
        """Same password produces different hashes due to random salt."""
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2, "bcrypt should produce different hashes (different salts)"

    def test_hash_password_never_equals_plain_text(self):
        """Stored hash never equals the plain-text password."""
        plain = "plaintextpassword"
        hashed = hash_password(plain)
        assert hashed != plain


class TestVerifyPassword:
    """Tests for verify_password() function."""

    def test_verify_password_correct_returns_true(self):
        """verify_password returns True for correct password (SC-HASH-2)."""
        plain = "correctpassword"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_password_wrong_returns_false(self):
        """verify_password returns False for wrong password."""
        plain = "correctpassword"
        hashed = hash_password(plain)
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty_string_returns_false(self):
        """verify_password returns False for empty password against a real hash."""
        hashed = hash_password("somepassword")
        assert verify_password("", hashed) is False

    def test_verify_password_round_trip(self):
        """Full round-trip: hash then verify with same password succeeds."""
        plain = "roundtriptest123!"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_password_returns_bool(self):
        """verify_password always returns a bool."""
        hashed = hash_password("test")
        result = verify_password("test", hashed)
        assert isinstance(result, bool)
