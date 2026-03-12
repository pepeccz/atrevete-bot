"""
Database package — SQLAlchemy models and connection utilities.

Core exports:
- ConversationHistory: Parent record for a conversation session (1 row per conversation)
- ConversationMessage: Individual messages within a conversation (1 row per message)
- GoogleOAuthCredential: Encrypted OAuth2 tokens for Google Calendar access

All other models are imported directly from database.models.
"""

from database.models import ConversationHistory, ConversationMessage, GoogleOAuthCredential

__all__ = [
    "ConversationHistory",
    "ConversationMessage",
    "GoogleOAuthCredential",
]
