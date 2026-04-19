"""Shared utilities for mode nodes built on top of ``create_agent``.

These helpers are not specific to any single mode or to the first-turn intro
prepend — they live here so each mode doesn't carry a private copy.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage


def extract_final_text(result: Any) -> str:
    """Return the last ``AIMessage`` content from a ``create_agent`` result dict.

    ``create_agent`` returns a ``{"messages": [...]}`` dict where the final
    assistant response is the last ``AIMessage`` in the stream. This helper
    walks the list backwards and normalises both string-content and the
    multi-block list form into a plain string.
    """
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "\n".join(parts).strip()
    return ""


__all__ = ["extract_final_text"]
