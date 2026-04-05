"""
Unit tests for agent/config/__init__.py — BookingConfig YAML loader.

Covers:
- Defaults when YAML is missing
- Defaults when YAML is unparseable
- Valid YAML overrides defaults
- Per-key fallback for invalid int (out of range)
- Per-key fallback for invalid enum value
- Partial invalid: bad key uses default, good key is kept
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, mock_open, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing the module under test
# ---------------------------------------------------------------------------

if "langchain_core" not in sys.modules:
    sys.modules["langchain_core"] = ModuleType("langchain_core")

if "langchain_core.messages" not in sys.modules:
    messages_stub = ModuleType("langchain_core.messages")
    for _cls in ("SystemMessage", "HumanMessage", "AIMessage", "ToolMessage"):

        class _Msg:
            def __init__(self, content=""):
                self.content = content

        _Msg.__name__ = _cls
        setattr(messages_stub, _cls, _Msg)
    sys.modules["langchain_core.messages"] = messages_stub

if "agent.state.schemas" not in sys.modules:
    schemas_stub = ModuleType("agent.state.schemas")
    schemas_stub.ConversationState = dict
    sys.modules["agent.state.schemas"] = schemas_stub

# ---------------------------------------------------------------------------
# Now safe to import
# ---------------------------------------------------------------------------

from agent.config import (  # noqa: E402
    BookingConfig,
    SlotStrategy,
    ToolChoicePolicy,
    _load_booking_config_from_disk,
    get_booking_config,
    invalidate_booking_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_YAML = """\
max_slots_to_present: 8
slot_diversification_strategy: "time_spread"
auto_search_extra_days: 7
tool_choice_policy: "always_force"
"""

_MODULE = "agent.config"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBookingConfigDefaults:
    """Verify all fields have the documented safe defaults."""

    def test_default_values(self):
        cfg = BookingConfig()
        assert cfg.max_slots_to_present == 5
        assert cfg.slot_diversification_strategy == SlotStrategy.ONE_PER_STYLIST
        assert cfg.auto_search_extra_days == 3
        assert cfg.tool_choice_policy == ToolChoicePolicy.NEVER_FORCE


class TestLoadBookingConfigFromDisk:
    """Unit tests for _load_booking_config_from_disk()."""

    def test_defaults_when_yaml_missing(self):
        """When booking.yaml does not exist, all fields return defaults."""
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = False
            cfg = _load_booking_config_from_disk()

        assert cfg == BookingConfig()

    def test_defaults_when_yaml_unparseable(self):
        """When open() returns garbage YAML, all fields return defaults."""
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=": : invalid: [[")):
                cfg = _load_booking_config_from_disk()

        assert cfg == BookingConfig()

    def test_defaults_when_open_raises(self):
        """When open() raises an OSError, all fields return defaults."""
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", side_effect=OSError("disk error")):
                cfg = _load_booking_config_from_disk()

        assert cfg == BookingConfig()

    def test_defaults_when_yaml_root_is_not_dict(self):
        """When YAML parses to a non-dict (e.g. a list), all fields return defaults."""
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data="- item1\n- item2\n")):
                cfg = _load_booking_config_from_disk()

        assert cfg == BookingConfig()

    def test_valid_yaml_overrides_defaults(self):
        """All four keys present and valid → values override defaults."""
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=_VALID_YAML)):
                cfg = _load_booking_config_from_disk()

        assert cfg.max_slots_to_present == 8
        assert cfg.slot_diversification_strategy == SlotStrategy.TIME_SPREAD
        assert cfg.auto_search_extra_days == 7
        assert cfg.tool_choice_policy == ToolChoicePolicy.ALWAYS_FORCE

    def test_invalid_int_falls_back_to_default(self):
        """max_slots_to_present: 999 exceeds le=20 → field falls back to default 5."""
        yaml_data = "max_slots_to_present: 999\n"
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=yaml_data)):
                cfg = _load_booking_config_from_disk()

        assert cfg.max_slots_to_present == 5

    def test_invalid_enum_falls_back_to_default(self):
        """slot_diversification_strategy: 'random' is not a valid SlotStrategy → default."""
        yaml_data = 'slot_diversification_strategy: "random"\n'
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=yaml_data)):
                cfg = _load_booking_config_from_disk()

        assert cfg.slot_diversification_strategy == SlotStrategy.ONE_PER_STYLIST

    def test_partial_invalid_keeps_valid_keys(self):
        """One bad key falls back to default; valid key is preserved."""
        yaml_data = (
            "max_slots_to_present: 999\n"  # invalid — exceeds le=20
            "auto_search_extra_days: 10\n"  # valid
        )
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=yaml_data)):
                cfg = _load_booking_config_from_disk()

        # Bad key → default
        assert cfg.max_slots_to_present == 5
        # Good key → preserved
        assert cfg.auto_search_extra_days == 10

    def test_unknown_keys_are_ignored(self):
        """Extra keys not in BookingConfig are silently ignored (extra='ignore')."""
        yaml_data = "unknown_key: some_value\nmax_slots_to_present: 3\n"
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=yaml_data)):
                cfg = _load_booking_config_from_disk()

        assert cfg.max_slots_to_present == 3


class TestGetBookingConfig:
    """Tests for the async get_booking_config() cache wrapper."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Ensure each test starts with a cold cache."""
        invalidate_booking_config()
        yield
        invalidate_booking_config()

    @pytest.mark.asyncio
    async def test_returns_booking_config_instance(self):
        """get_booking_config() always returns a BookingConfig."""
        with patch(f"{_MODULE}._BOOKING_YAML") as mock_path:
            mock_path.exists.return_value = False
            cfg = await get_booking_config()

        assert isinstance(cfg, BookingConfig)

    @pytest.mark.asyncio
    async def test_cached_result_returned_on_second_call(self):
        """Second call returns the same object (cache hit, loader not called again)."""
        call_count = 0
        original_loader = _load_booking_config_from_disk

        def counting_loader():
            nonlocal call_count
            call_count += 1
            return original_loader()

        with patch(f"{_MODULE}._load_booking_config_from_disk", side_effect=counting_loader):
            cfg1 = await get_booking_config()
            cfg2 = await get_booking_config()

        assert cfg1 == cfg2
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_forces_reload(self):
        """After invalidate_booking_config(), the next call reloads from disk."""
        call_count = 0
        original_loader = _load_booking_config_from_disk

        def counting_loader():
            nonlocal call_count
            call_count += 1
            return original_loader()

        with patch(f"{_MODULE}._load_booking_config_from_disk", side_effect=counting_loader):
            await get_booking_config()
            invalidate_booking_config()
            await get_booking_config()

        assert call_count == 2
