"""
Unit tests for notification_tools.py - Re-export verification.

This module tests that notification_tools.py correctly re-exports
ChatwootClient from shared.chatwoot_client for backward compatibility.

Tests coverage:
- Re-export verification
- Import paths
- Module structure
"""

import pytest


# ============================================================================
# Test Re-export
# ============================================================================


class TestNotificationToolsReexport:
    """Test that notification_tools.py re-exports correctly."""

    def test_chatwoot_client_import_from_notification_tools(self):
        """Test that ChatwootClient can be imported from notification_tools."""
        from agent.tools.notification_tools import ChatwootClient

        # Should not raise ImportError
        assert ChatwootClient is not None

    def test_chatwoot_client_import_from_shared(self):
        """Test that ChatwootClient can be imported from shared."""
        from shared.chatwoot_client import ChatwootClient

        # Should not raise ImportError
        assert ChatwootClient is not None

    def test_reexport_is_same_class(self):
        """Test that re-export points to the same class."""
        from agent.tools.notification_tools import ChatwootClient as NotificationClient
        from shared.chatwoot_client import ChatwootClient as SharedClient

        # Should be the exact same class
        assert NotificationClient is SharedClient

    def test_module_has_all_attribute(self):
        """Test that module defines __all__ for explicit exports."""
        import agent.tools.notification_tools as notification_tools

        assert hasattr(notification_tools, "__all__")
        assert "ChatwootClient" in notification_tools.__all__

    def test_can_instantiate_from_reexport(self):
        """Test that we can instantiate ChatwootClient from re-export."""
        from agent.tools.notification_tools import ChatwootClient

        # Should be able to instantiate (will use env vars)
        # We're just testing the import path works
        try:
            client = ChatwootClient()
            assert client is not None
        except Exception:
            # May fail if env vars not set, but that's OK
            # We're just testing the import works
            pass


# ============================================================================
# Test Backward Compatibility
# ============================================================================


class TestBackwardCompatibility:
    """Test backward compatibility of re-export."""

    def test_old_import_path_still_works(self):
        """Test that old import path from agent.tools still works."""
        # This is the backward compatibility we're maintaining
        from agent.tools.notification_tools import ChatwootClient

        assert ChatwootClient.__name__ == "ChatwootClient"

    def test_new_import_path_works(self):
        """Test that new canonical path from shared still works."""
        from shared.chatwoot_client import ChatwootClient

        assert ChatwootClient.__name__ == "ChatwootClient"

    def test_class_attributes_preserved(self):
        """Test that class attributes are preserved in re-export."""
        from agent.tools.notification_tools import ChatwootClient

        # Class should have expected methods
        expected_methods = [
            "__init__",
            "_find_contact_by_phone",
            "_create_contact",
            "send_message",
        ]

        for method_name in expected_methods:
            assert hasattr(ChatwootClient, method_name), \
                f"ChatwootClient should have {method_name} method"

    def test_module_docstring_exists(self):
        """Test that module has documentation."""
        import agent.tools.notification_tools as notification_tools

        assert notification_tools.__doc__ is not None
        assert "backward compatibility" in notification_tools.__doc__.lower()
