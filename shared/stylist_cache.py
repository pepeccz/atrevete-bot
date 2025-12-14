"""
Stylist context cache - shared between API and Agent.

This module provides a lightweight cache storage for stylist context
that can be safely imported by both the API service and the Agent service
without causing dependency issues.

The cache stores formatted stylist data (markdown) used in LLM prompts.
TTL is managed by the consumer (agent/prompts/__init__.py).
"""

import logging

logger = logging.getLogger(__name__)

# Global cache storage (no heavy dependencies)
# - data: The cached stylist context string (markdown format)
# - expires_at: datetime when cache expires (managed by agent)
_STYLIST_CONTEXT_CACHE: dict = {
    "data": None,
    "expires_at": None,
}


def clear_stylist_context_cache() -> None:
    """
    Clear the stylist context cache.

    This forces the next call to load_stylist_context() in the agent
    to query the database instead of using cached data.

    Useful when:
    - Stylist data has been modified and needs immediate reflection
    - Admin wants to force a refresh of LLM context
    """
    _STYLIST_CONTEXT_CACHE["data"] = None
    _STYLIST_CONTEXT_CACHE["expires_at"] = None
    logger.info("Stylist context cache cleared")


def get_cache() -> dict:
    """
    Get the cache dictionary for use by the agent.

    Returns the internal cache dict that the agent can extend
    with additional fields (like asyncio.Lock for thread safety).
    """
    return _STYLIST_CONTEXT_CACHE
