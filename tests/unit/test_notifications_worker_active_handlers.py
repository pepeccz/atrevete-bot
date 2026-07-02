"""Unit tests for notifications_worker._active_handlers() refactor.

RED phase: written before _active_handlers() exists in notifications_worker.py.
Covers S3-R1, S3-R11, S3-R13 per spec obs #7262.
"""

from __future__ import annotations

from types import SimpleNamespace


def _settings(auto_cancel_enabled: bool):
    return SimpleNamespace(AUTO_CANCEL_ENABLED=auto_cancel_enabled)


# ---------------------------------------------------------------------------
# _active_handlers() — flag=False
# ---------------------------------------------------------------------------


def test_active_handlers_flag_false_excludes_auto_cancel_handlers():
    """When AUTO_CANCEL_ENABLED=False, final_warning and auto_cancel MUST NOT be active."""
    from agent.workers.notifications_worker import _active_handlers

    handlers = _active_handlers(_settings(False))

    assert "final_warning" not in handlers, "final_warning must be dormant when flag=False"
    assert "auto_cancel" not in handlers, "auto_cancel must be dormant when flag=False"


def test_active_handlers_flag_false_includes_base_handlers():
    """When AUTO_CANCEL_ENABLED=False, the 3 base handlers are always active (S3-R13)."""
    from agent.workers.notifications_worker import _active_handlers

    handlers = _active_handlers(_settings(False))

    assert "reminder_24h" in handlers, "reminder_24h must always be active"
    assert "confirm_48h" in handlers, "confirm_48h must always be active"
    assert "paused_24h" in handlers, "paused_24h must always be active"


# ---------------------------------------------------------------------------
# _active_handlers() — flag=True
# ---------------------------------------------------------------------------


def test_active_handlers_flag_true_includes_auto_cancel_handlers():
    """When AUTO_CANCEL_ENABLED=True, final_warning and auto_cancel MUST be active."""
    from agent.workers.notifications_worker import _active_handlers

    handlers = _active_handlers(_settings(True))

    assert "final_warning" in handlers, "final_warning must be active when flag=True"
    assert "auto_cancel" in handlers, "auto_cancel must be active when flag=True"


def test_active_handlers_flag_true_includes_all_handlers():
    """When AUTO_CANCEL_ENABLED=True, all 5 handlers are present."""
    from agent.workers.notifications_worker import _active_handlers

    handlers = _active_handlers(_settings(True))

    assert "reminder_24h" in handlers
    assert "confirm_48h" in handlers
    assert "paused_24h" in handlers
    assert "final_warning" in handlers
    assert "auto_cancel" in handlers


def test_active_handlers_each_handler_name_matches_key():
    """handler.name == dict key for every entry in _active_handlers()."""
    from agent.workers.notifications_worker import _active_handlers

    for enabled in (False, True):
        handlers = _active_handlers(_settings(enabled))
        for key, handler in handlers.items():
            assert handler.name == key, f"handler.name={handler.name!r} must equal key={key!r}"


# ---------------------------------------------------------------------------
# Toggle test: kill-switch immediacy (S3-R11)
# ---------------------------------------------------------------------------


def test_active_handlers_toggle_returns_different_dicts():
    """Two sequential calls with True/False yield different handler sets (kill-switch, S3-R11)."""
    from agent.workers.notifications_worker import _active_handlers

    with_flag = _active_handlers(_settings(True))
    without_flag = _active_handlers(_settings(False))

    # auto_cancel handlers present in one set, absent in the other
    assert "auto_cancel" in with_flag
    assert "auto_cancel" not in without_flag
    assert "final_warning" in with_flag
    assert "final_warning" not in without_flag


# ---------------------------------------------------------------------------
# Backward-compat: module-level HANDLERS alias still resolves
# ---------------------------------------------------------------------------


def test_module_level_handlers_alias_exists():
    """The module-level HANDLERS dict must still be importable (backward compat)."""
    from agent.workers.notifications_worker import HANDLERS

    assert isinstance(HANDLERS, dict)
    # Must at least contain the 3 base handlers (flag defaults to False in tests)
    for key in ("reminder_24h", "confirm_48h", "paused_24h"):
        assert key in HANDLERS, f"base handler {key!r} must be in HANDLERS alias"


def test_module_level_handlers_all_handlers_are_callable():
    """Every handler in the HANDLERS alias has callable fn fields."""
    from agent.workers.notifications_worker import HANDLERS

    for key, handler in HANDLERS.items():
        assert callable(handler.query_fn), f"{key}.query_fn must be callable"
        assert callable(handler.send_fn), f"{key}.send_fn must be callable"
        assert callable(handler.mark_sent_fn), f"{key}.mark_sent_fn must be callable"
        assert callable(handler.mark_failed_fn), f"{key}.mark_failed_fn must be callable"
