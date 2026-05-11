"""Bcrypt password hashing helpers.

Provides hash_password() and verify_password() for use in admin authentication
and user-CRUD operations.

Security requirements:
- bcrypt cost factor >= 12 (NFR-2, SC-HASH-1)
- Plain-text passwords are NEVER stored or returned
- Uses bcrypt library directly (not via passlib API)
"""

from __future__ import annotations

import bcrypt as _bcrypt

# Default cost factor — must be >= 12 per NFR-2.
_BCRYPT_ROUNDS: int = 12


def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt.

    Args:
        plain: The plain-text password to hash.

    Returns:
        A bcrypt hash string starting with ``$2b$``.

    Note:
        Cost factor is fixed at 12 (NFR-2). Each call produces a unique
        hash because bcrypt generates a fresh random salt internally.
    """
    hashed_bytes = _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed_bytes.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    Args:
        plain: The plain-text password to verify.
        hashed: The stored bcrypt hash.

    Returns:
        ``True`` if the password matches the hash, ``False`` otherwise.
        Never raises on invalid input — returns ``False`` for any error.
    """
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
