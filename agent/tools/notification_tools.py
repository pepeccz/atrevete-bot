"""
Notification tools for sending messages via Chatwoot.

This module re-exports the ChatwootClient from shared for backward compatibility.
The actual implementation is in shared/chatwoot_client.py.
"""

# Re-export ChatwootClient for backward compatibility with existing imports
from shared.chatwoot_client import ChatwootClient

__all__ = ["ChatwootClient"]
