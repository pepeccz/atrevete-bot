"""
Fernet symmetric encryption for sensitive values (OAuth2 tokens, etc).

Key derivation: PBKDF2-HMAC-SHA256 from ADMIN_JWT_SECRET.
Same secret → same derived key → deterministic encrypt/decrypt.

Usage:
    from shared.encryption import encrypt_token, decrypt_token

    ciphertext = encrypt_token("ya29.access-token-value")
    plaintext = decrypt_token(ciphertext)  # back to original
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from shared.config import get_settings

# Fixed salt — deterministic key derivation across restarts.
# Changing this salt invalidates ALL previously encrypted tokens.
_SALT = b"atrevete-bot-fernet-v1"


def _get_fernet() -> Fernet:
    """
    Derive a Fernet instance from ADMIN_JWT_SECRET.

    Uses PBKDF2-HMAC-SHA256 with a fixed salt to produce a 32-byte key, then
    base64url-encodes it to produce a valid Fernet key (44-char URL-safe base64).

    The same ADMIN_JWT_SECRET always produces the same Fernet key, so previously
    encrypted tokens remain decryptable as long as the secret is unchanged.
    """
    settings = get_settings()
    secret = settings.ADMIN_JWT_SECRET.encode()
    key_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        secret,
        _SALT,
        iterations=100_000,
        dklen=32,
    )
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_token(plaintext: str) -> str:
    """
    Encrypt a token string using Fernet symmetric encryption.

    Args:
        plaintext: The raw token string to encrypt (e.g., Google OAuth access token).

    Returns:
        A base64-encoded ciphertext string suitable for storage in the database.
        The returned string is safe to store in Text/VARCHAR columns.

    Example:
        ciphertext = encrypt_token("ya29.access-token...")
    """
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """
    Decrypt a token string that was previously encrypted with encrypt_token().

    Args:
        ciphertext: The base64-encoded ciphertext string retrieved from the database.

    Returns:
        The original plaintext token string.

    Raises:
        cryptography.fernet.InvalidToken: If the ciphertext was tampered with,
            the key has changed (ADMIN_JWT_SECRET changed), or the token is corrupted.

    Example:
        plaintext = decrypt_token(row.encrypted_access_token)
    """
    return _get_fernet().decrypt(ciphertext.encode()).decode()
