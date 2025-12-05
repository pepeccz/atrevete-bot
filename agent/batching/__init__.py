"""
Message Batching Module.

Provides functionality to batch multiple messages within a time window
before processing them as a single combined input.
"""

from agent.batching.message_batcher import MessageBatcher

__all__ = ["MessageBatcher"]
