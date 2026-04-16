"""Shared helpers for offline middleware tests.

``FakeMessagesListChatModel`` raises ``NotImplementedError`` from ``bind_tools``;
``create_agent`` invokes ``bind_tools`` unconditionally, so any offline harness
that wants to drive a ``create_agent`` end-to-end needs a thin subclass with a
no-op ``bind_tools``. That fact was the single biggest surprise from the
migration spike — documented in ``spikes/create_agent_migration/RESULTS.md``.
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel


class ScriptedModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel that tolerates ``bind_tools()`` (no-op)."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # type: ignore[override]
        return self


__all__ = ["ScriptedModel"]
