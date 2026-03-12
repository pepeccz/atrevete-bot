"""
API services package — business logic layer for the FastAPI application.

Modules:
    conversation_delete_service: Atomic delete of a conversation from DB + Redis.
"""

from api.services.conversation_delete_service import DeleteResult, delete_conversation

__all__ = [
    "DeleteResult",
    "delete_conversation",
]
