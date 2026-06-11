"""
Unit tests for agent/utils/monitoring.py — C3 race-condition fix + keyless guard (U1).

Bug C3: get_langfuse_handler() used to mutate 6 process-global env vars
(LANGFUSE_SESSION_ID, LANGFUSE_USER_ID, LANGFUSE_TAGS, etc.) on every call.
Under concurrent workers, per-conversation session/user/tag values were
written to a shared global and could bleed into another conversation's trace.

Fix: session_id, user_id, tags are passed as kwargs to propagate_attributes()
(the Langfuse 4.x OTEL context manager) instead of mutating os.environ.
Credentials (public_key, secret_key, host) are configured once at module
level via env vars — the Docker deploy sets them and they don't change
per-call.

U1 (keyless guard): get_langfuse_handler() returns (None, None) when either
Langfuse key is absent, without constructing a CallbackHandler or making any
network call. Keys-present path is byte-identical to pre-guard.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot_langfuse_env() -> dict[str, str]:
    """Return current LANGFUSE_* env vars as a dict snapshot."""
    return {k: v for k, v in os.environ.items() if k.startswith("LANGFUSE_")}


# ---------------------------------------------------------------------------
# Test 1 — no global env mutation
# ---------------------------------------------------------------------------


def test_get_langfuse_handler_does_not_mutate_global_environ(monkeypatch):
    """
    get_langfuse_handler() MUST NOT write LANGFUSE_SESSION_ID, LANGFUSE_USER_ID,
    or LANGFUSE_TAGS to os.environ.

    The function must return (CallbackHandler, propagate_attributes_ctx) where
    per-call context is scoped to the propagate_attributes context manager.
    """
    # Arrange: seed credentials (static, set once at deploy)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_SESSION_ID", raising=False)
    monkeypatch.delenv("LANGFUSE_USER_ID", raising=False)
    monkeypatch.delenv("LANGFUSE_TAGS", raising=False)

    captured_kwargs: list[dict] = []

    class _FakeHandler:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.append(kwargs)

    class _FakePropagateCtx:
        """Fake context manager returned by propagate_attributes."""

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    propagate_calls: list[dict] = []

    def _fake_propagate_attributes(**kwargs):
        propagate_calls.append(kwargs)
        return _FakePropagateCtx(**kwargs)

    # Stub out both CallbackHandler and propagate_attributes so no real SDK call
    with (
        patch("agent.utils.monitoring.CallbackHandler", _FakeHandler),
        patch("agent.utils.monitoring.propagate_attributes", _fake_propagate_attributes),
    ):
        from agent.utils.monitoring import get_langfuse_handler

        snapshot_before = _snapshot_langfuse_env()
        result = get_langfuse_handler(
            conversation_id="conv-1",
            customer_phone="+34111111111",
            customer_name="Alice",
        )
        snapshot_after = _snapshot_langfuse_env()

    # The function must return a 2-tuple (handler, ctx_manager)
    assert isinstance(
        result, tuple
    ), "get_langfuse_handler must return (CallbackHandler, propagate_attributes_ctx)"
    handler, ctx = result

    # os.environ MUST be unchanged for per-call keys
    per_call_keys = {"LANGFUSE_SESSION_ID", "LANGFUSE_USER_ID", "LANGFUSE_TAGS"}
    new_keys = set(snapshot_after) - set(snapshot_before)
    mutated_per_call = new_keys & per_call_keys
    assert (
        not mutated_per_call
    ), f"get_langfuse_handler mutated global os.environ for keys: {mutated_per_call}"

    # propagate_attributes must have been called with correct per-call values
    assert len(propagate_calls) == 1, "propagate_attributes must be called once"
    call = propagate_calls[0]
    assert (
        call.get("session_id") == "conv-1"
    ), f"Expected session_id='conv-1', got {call.get('session_id')!r}"
    assert (
        call.get("user_id") == "+34111111111"
    ), f"Expected user_id='+34111111111', got {call.get('user_id')!r}"
    tags = call.get("tags", [])
    assert any(
        "customer:Alice" in t for t in tags
    ), f"Expected 'customer:Alice' in tags, got {tags!r}"


# ---------------------------------------------------------------------------
# Test 2 — concurrent calls do not cross-contaminate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_langfuse_handler_concurrent_calls_do_not_cross_contaminate(monkeypatch):
    """
    Two concurrent calls with different conversation_id/customer_phone MUST NOT
    mix each other's session_id / user_id in their propagate_attributes context.

    This proves no shared global-state contamination.
    """
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_SESSION_ID", raising=False)
    monkeypatch.delenv("LANGFUSE_USER_ID", raising=False)
    monkeypatch.delenv("LANGFUSE_TAGS", raising=False)

    class _FakeHandler:
        def __init__(self, **kwargs: Any) -> None:
            pass

    propagate_calls: list[dict] = []

    class _FakePropagateCtx:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    def _fake_propagate(**kwargs):
        propagate_calls.append(dict(kwargs))
        return _FakePropagateCtx(**kwargs)

    with (
        patch("agent.utils.monitoring.CallbackHandler", _FakeHandler),
        patch("agent.utils.monitoring.propagate_attributes", _fake_propagate),
    ):
        from agent.utils.monitoring import get_langfuse_handler

        async def _call(conv_id: str, phone: str) -> tuple:
            return get_langfuse_handler(
                conversation_id=conv_id,
                customer_phone=phone,
                customer_name=None,
            )

        # Fire both concurrently
        results = await asyncio.gather(
            _call("conv-A", "+34000000001"),
            _call("conv-B", "+34000000002"),
        )

    # Each call captured its own propagate invocation
    assert (
        len(propagate_calls) == 2
    ), f"Expected 2 propagate_attributes calls, got {len(propagate_calls)}"

    # Extract by session_id — order is non-deterministic
    by_session = {c["session_id"]: c for c in propagate_calls}
    assert "conv-A" in by_session, "conv-A not found in propagate calls"
    assert "conv-B" in by_session, "conv-B not found in propagate calls"

    assert (
        by_session["conv-A"]["user_id"] == "+34000000001"
    ), f"conv-A user_id cross-contaminated: {by_session['conv-A']['user_id']!r}"
    assert (
        by_session["conv-B"]["user_id"] == "+34000000002"
    ), f"conv-B user_id cross-contaminated: {by_session['conv-B']['user_id']!r}"


# ---------------------------------------------------------------------------
# Test 3 — exception propagation
# ---------------------------------------------------------------------------


def test_get_langfuse_handler_raises_when_callback_handler_fails(monkeypatch):
    """
    When CallbackHandler.__init__ raises, the exception must propagate
    (so the caller can catch it and continue without tracing).
    """
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    class _BrokenHandler:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("SDK init failure")

    class _FakePropagateCtx:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def _fake_propagate(**kwargs):
        return _FakePropagateCtx(**kwargs)

    with (
        patch("agent.utils.monitoring.CallbackHandler", _BrokenHandler),
        patch("agent.utils.monitoring.propagate_attributes", _fake_propagate),
    ):
        from agent.utils.monitoring import get_langfuse_handler

        with pytest.raises(RuntimeError, match="SDK init failure"):
            get_langfuse_handler(
                conversation_id="conv-err",
                customer_phone="+34999999999",
                customer_name=None,
            )


# ---------------------------------------------------------------------------
# Test 5 — ctx is a SYNC context manager (regression guard)
# ---------------------------------------------------------------------------


def test_get_langfuse_handler_returns_sync_context_manager(monkeypatch):
    """
    Regression: prod incident 2026-06-07 — agent/main.py wrapped the returned
    ctx with `async with`, but `propagate_attributes()` returns a SYNC context
    manager. Python raised TypeError on every turn and users got the fallback
    "Lo siento, tuve un problema técnico...".

    Guard: the returned ctx must implement __enter__/__exit__ (sync protocol)
    and must NOT implement __aenter__/__aexit__.
    """
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    from agent.utils.monitoring import get_langfuse_handler

    _, ctx = get_langfuse_handler(
        conversation_id="conv-sync",
        customer_phone="+34111111111",
        customer_name=None,
    )

    assert hasattr(ctx, "__enter__"), "ctx must support sync `with` protocol"
    assert hasattr(ctx, "__exit__"), "ctx must support sync `with` protocol"
    assert not hasattr(ctx, "__aenter__"), (
        "ctx must NOT be an async context manager — agent/main.py uses sync `with`"
    )
    assert not hasattr(ctx, "__aexit__"), (
        "ctx must NOT be an async context manager — agent/main.py uses sync `with`"
    )


# ---------------------------------------------------------------------------
# Tests 6-8 — U1 keyless guard
# ---------------------------------------------------------------------------


def test_get_langfuse_handler_returns_none_tuple_when_both_keys_absent(monkeypatch):
    """
    U1: when both LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are absent,
    get_langfuse_handler() must return (None, None) without constructing a
    CallbackHandler or making any network call.
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    # Invalidate the settings cache so monkeypatched env is visible
    from shared.config import get_settings

    get_settings.cache_clear()

    handler_constructed = []

    class _SpyHandler:
        def __init__(self, **kwargs: Any) -> None:
            handler_constructed.append(kwargs)

    with patch("agent.utils.monitoring.CallbackHandler", _SpyHandler):
        from agent.utils.monitoring import get_langfuse_handler

        result = get_langfuse_handler(
            conversation_id="conv-keyless",
            customer_phone="+34000000001",
        )

    get_settings.cache_clear()  # restore cache state for other tests

    assert result == (None, None), f"Expected (None, None) when keys absent, got {result!r}"
    assert not handler_constructed, "CallbackHandler must NOT be constructed when keys absent"


def test_get_langfuse_handler_returns_none_tuple_when_only_public_key_set(monkeypatch):
    """
    U1 edge case: only PUBLIC_KEY present, SECRET_KEY absent → (None, None).
    Partial credentials are treated as absent (guard is 'or'-based).
    """
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-only")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    from shared.config import get_settings

    get_settings.cache_clear()

    handler_constructed = []

    class _SpyHandler:
        def __init__(self, **kwargs: Any) -> None:
            handler_constructed.append(kwargs)

    with patch("agent.utils.monitoring.CallbackHandler", _SpyHandler):
        from agent.utils.monitoring import get_langfuse_handler

        result = get_langfuse_handler(
            conversation_id="conv-partial",
            customer_phone="+34000000002",
        )

    get_settings.cache_clear()

    assert result == (None, None), (
        f"Expected (None, None) when only PUBLIC_KEY set, got {result!r}"
    )
    assert not handler_constructed, "CallbackHandler must NOT be constructed with partial keys"


def test_get_langfuse_handler_builds_handler_when_both_keys_present(monkeypatch):
    """
    U1 regression guard: when both keys are valid non-empty strings,
    get_langfuse_handler() must return a (CallbackHandler, ctx) tuple — the
    keys-present path must be byte-identical to pre-guard behavior.
    """
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-valid")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-valid")

    from shared.config import get_settings

    get_settings.cache_clear()

    class _FakeHandler:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakePropagateCtx:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def _fake_propagate(**kwargs):
        return _FakePropagateCtx(**kwargs)

    with (
        patch("agent.utils.monitoring.CallbackHandler", _FakeHandler),
        patch("agent.utils.monitoring.propagate_attributes", _fake_propagate),
    ):
        from agent.utils.monitoring import get_langfuse_handler

        handler, ctx = get_langfuse_handler(
            conversation_id="conv-valid",
            customer_phone="+34000000003",
            customer_name="Test User",
        )

    get_settings.cache_clear()

    assert isinstance(handler, _FakeHandler), (
        f"Expected CallbackHandler instance when both keys present, got {type(handler)!r}"
    )
    assert ctx is not None, "ctx must not be None when both keys present"
