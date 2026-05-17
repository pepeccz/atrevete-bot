"""
Tests for escalation_service.py - Human escalation workflow.

This module tests the escalation service that handles human handoff:
- perform_escalation: Central 5-step pipeline with graceful degradation
- disable_bot_in_chatwoot: Disable bot via atencion_automatica attribute
- create_escalation_notification: Create admin panel notification
- trigger_escalation: Backward-compatible wrapper (delegates to perform_escalation)

Coverage:
- perform_escalation: all steps, duplicate prevention, partial failures
- Chatwoot bot disable success/failure
- Notification creation with customer lookup
- Notification creation with conversation context
- Reason-to-notification-type mapping
- Error handling and graceful degradation
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.services.escalation_service import (
    ESCALATION_TITLES,
    REASON_DESCRIPTIONS,
    REASON_TO_NOTIFICATION_TYPE,
    EscalationResult,
    create_escalation_notification,
    disable_bot_in_chatwoot,
    perform_escalation,
    trigger_escalation,
)
from database.models import NotificationType

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ============================================================================
# Test Reason Mappings
# ============================================================================


class TestReasonMappings:
    """Test mapping of escalation reasons to notification types."""

    def test_all_predefined_reasons_mapped(self):
        """Verify all predefined reasons have notification type mapping."""
        expected_reasons = [
            "medical_consultation",
            "ambiguity",
            "manual_request",
            "technical_error",
            "auto_escalation",
        ]

        for reason in expected_reasons:
            assert reason in REASON_TO_NOTIFICATION_TYPE, f"Missing mapping for {reason}"

    def test_reason_mapping_to_correct_types(self):
        """Verify reasons map to correct notification types."""
        assert (
            REASON_TO_NOTIFICATION_TYPE["medical_consultation"]
            == NotificationType.ESCALATION_MEDICAL
        )
        assert REASON_TO_NOTIFICATION_TYPE["ambiguity"] == NotificationType.ESCALATION_AMBIGUITY
        assert REASON_TO_NOTIFICATION_TYPE["manual_request"] == NotificationType.ESCALATION_MANUAL
        assert (
            REASON_TO_NOTIFICATION_TYPE["technical_error"] == NotificationType.ESCALATION_TECHNICAL
        )
        assert REASON_TO_NOTIFICATION_TYPE["auto_escalation"] == NotificationType.ESCALATION_AUTO

    def test_default_mapping_exists(self):
        """Verify default mapping exists for unknown reasons."""
        assert "default" in REASON_TO_NOTIFICATION_TYPE
        assert REASON_TO_NOTIFICATION_TYPE["default"] == NotificationType.ESCALATION_MANUAL

    def test_all_notification_types_have_titles(self):
        """Verify all escalation notification types have titles."""
        escalation_types = [
            NotificationType.ESCALATION_MANUAL,
            NotificationType.ESCALATION_TECHNICAL,
            NotificationType.ESCALATION_AUTO,
            NotificationType.ESCALATION_MEDICAL,
            NotificationType.ESCALATION_AMBIGUITY,
        ]

        for ntype in escalation_types:
            assert ntype in ESCALATION_TITLES, f"Missing title for {ntype}"
            assert len(ESCALATION_TITLES[ntype]) > 0

    def test_all_reasons_have_descriptions(self):
        """Verify all reasons have human-readable descriptions."""
        for reason in REASON_TO_NOTIFICATION_TYPE:
            if reason != "default":
                assert reason in REASON_DESCRIPTIONS, f"Missing description for {reason}"


# ============================================================================
# Test disable_bot_in_chatwoot
# ============================================================================


class TestDisableBotInChatwoot:
    """Test Chatwoot bot disable functionality."""

    @pytest.mark.asyncio
    async def test_disable_bot_success(self):
        """Verify bot is disabled successfully."""
        with patch("shared.chatwoot_client.ChatwootClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await disable_bot_in_chatwoot("12345")

            assert result is True
            mock_client.update_conversation_attributes.assert_called_once_with(
                conversation_id=12345,
                attributes={"atencion_automatica": False},
            )

    @pytest.mark.asyncio
    async def test_disable_bot_converts_string_to_int(self):
        """Verify conversation_id is converted from string to int."""
        with patch("shared.chatwoot_client.ChatwootClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            await disable_bot_in_chatwoot("99999")

            call_args = mock_client.update_conversation_attributes.call_args
            assert call_args[1]["conversation_id"] == 99999

    @pytest.mark.asyncio
    async def test_disable_bot_failure_returns_false(self):
        """Verify returns False when Chatwoot call fails."""
        with patch("shared.chatwoot_client.ChatwootClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.update_conversation_attributes.side_effect = Exception("API Error")
            mock_client_class.return_value = mock_client

            result = await disable_bot_in_chatwoot("12345")

            assert result is False

    @pytest.mark.asyncio
    async def test_disable_bot_logs_success(self):
        """Verify successful disable is logged."""
        with patch("shared.chatwoot_client.ChatwootClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            with patch("agent.services.escalation_service.logger") as mock_logger:
                await disable_bot_in_chatwoot("12345")

                mock_logger.info.assert_called_once()
                call_args = mock_logger.info.call_args[0][0]
                assert "Bot disabled" in call_args
                assert "12345" in call_args

    @pytest.mark.asyncio
    async def test_disable_bot_logs_error(self):
        """Verify errors are logged."""
        with patch("shared.chatwoot_client.ChatwootClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.update_conversation_attributes.side_effect = Exception("Network timeout")
            mock_client_class.return_value = mock_client

            with patch("agent.services.escalation_service.logger") as mock_logger:
                await disable_bot_in_chatwoot("12345")

                mock_logger.error.assert_called_once()
                call_args = mock_logger.error.call_args[0][0]
                assert "Failed to disable bot" in call_args


# ============================================================================
# Test create_escalation_notification
# ============================================================================


class TestCreateEscalationNotification:
    """Test notification creation functionality."""

    @pytest.fixture
    def mock_customer(self):
        """Create mock customer for testing."""
        customer = MagicMock()
        customer.id = uuid4()
        customer.phone = "+34612345678"
        customer.first_name = "María"
        customer.last_name = "García"
        return customer

    @pytest.mark.asyncio
    async def test_notification_created_with_customer(self, mock_customer):
        """Verify notification is created when customer exists."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = mock_customer

        mock_notification = MagicMock()
        mock_notification.id = notification_id

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
            )

            assert result is not None
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_created_without_customer(self):
        """Verify notification is created even when customer not found."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34999999999",
                conversation_id="12345",
            )

            assert result is not None
            mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_includes_conversation_context(self, mock_customer):
        """Verify notification message includes conversation context."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        captured_notification = None

        def capture_notification(n):
            nonlocal captured_notification
            captured_notification = n

        mock_session.add = capture_notification

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            context = [
                {"role": "user", "content": "Hola, quiero hablar con alguien"},
                {"role": "assistant", "content": "Claro, te conecto"},
            ]

            await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
                conversation_context=context,
            )

            assert captured_notification is not None
            assert "Contexto reciente" in captured_notification.message
            assert "user:" in captured_notification.message
            assert "assistant:" in captured_notification.message

    @pytest.mark.asyncio
    async def test_notification_truncates_long_messages(self, mock_customer):
        """Verify long messages in context are truncated."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        captured_notification = None

        def capture_notification(n):
            nonlocal captured_notification
            captured_notification = n

        mock_session.add = capture_notification

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            long_message = "x" * 200  # Very long message
            context = [{"role": "user", "content": long_message}]

            await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
                conversation_context=context,
            )

            assert captured_notification is not None
            assert "..." in captured_notification.message
            # Original 200 chars should be truncated to 100 + "..."
            assert long_message not in captured_notification.message

    @pytest.mark.asyncio
    async def test_notification_uses_correct_type_for_reason(self, mock_customer):
        """Verify notification uses correct type based on reason."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        captured_notification = None

        def capture_notification(n):
            nonlocal captured_notification
            captured_notification = n

        mock_session.add = capture_notification

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            # Test medical reason
            await create_escalation_notification(
                reason="medical_consultation",
                customer_phone="+34612345678",
                conversation_id="12345",
            )

            assert captured_notification.type == NotificationType.ESCALATION_MEDICAL

    @pytest.mark.asyncio
    async def test_notification_uses_default_for_unknown_reason(self, mock_customer):
        """Verify unknown reasons fall back to default type."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        captured_notification = None

        def capture_notification(n):
            nonlocal captured_notification
            captured_notification = n

        mock_session.add = capture_notification

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await create_escalation_notification(
                reason="unknown_reason_xyz",
                customer_phone="+34612345678",
                conversation_id="12345",
            )

            # Should fall back to ESCALATION_MANUAL
            assert captured_notification.type == NotificationType.ESCALATION_MANUAL

    @pytest.mark.asyncio
    async def test_notification_returns_none_on_error(self):
        """Verify returns None when database error occurs."""
        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.side_effect = Exception("DB error")

            result = await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_notification_entity_type_is_conversation(self, mock_customer):
        """Verify notification entity_type is 'conversation'."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = mock_customer

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        captured_notification = None

        def capture_notification(n):
            nonlocal captured_notification
            captured_notification = n

        mock_session.add = capture_notification

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
            )

            assert captured_notification.entity_type == "conversation"


# ============================================================================
# Test trigger_escalation (backward-compat wrapper)
# ============================================================================


class TestTriggerEscalation:
    """Test trigger_escalation — backward-compatible wrapper around perform_escalation."""

    @pytest.mark.asyncio
    async def test_trigger_escalation_success(self):
        """trigger_escalation returns expected legacy keys on success."""
        escalation_id = uuid4()
        mock_result = EscalationResult(
            success=True,
            escalation_id=escalation_id,
            steps_completed=["disable_bot", "labels", "private_note", "db_record"],
        )
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await trigger_escalation(
                reason="manual_request",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        assert result["chatwoot_disabled"] is True
        assert result["notification_id"] == escalation_id
        assert result["webhooks_triggered"] == []

    @pytest.mark.asyncio
    async def test_trigger_escalation_disable_bot_failed(self):
        """chatwoot_disabled is False when disable_bot step failed."""
        mock_result = EscalationResult(
            success=False,
            steps_completed=["labels"],
            steps_failed=["disable_bot"],
        )
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await trigger_escalation(
                reason="manual_request",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        assert result["chatwoot_disabled"] is False

    @pytest.mark.asyncio
    async def test_trigger_escalation_notification_fails(self):
        """notification_id is None when db_record step did not complete."""
        mock_result = EscalationResult(
            success=True,
            escalation_id=None,
            steps_completed=["disable_bot"],
            steps_failed=["db_record"],
        )
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await trigger_escalation(
                reason="manual_request",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        assert result["chatwoot_disabled"] is True
        assert result["notification_id"] is None

    @pytest.mark.asyncio
    async def test_trigger_escalation_both_fail(self):
        """All keys present even when all steps fail."""
        mock_result = EscalationResult(
            success=False,
            escalation_id=None,
            steps_completed=[],
            steps_failed=["disable_bot", "db_record"],
        )
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await trigger_escalation(
                reason="manual_request",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        assert result["chatwoot_disabled"] is False
        assert result["notification_id"] is None
        assert result["webhooks_triggered"] == []

    @pytest.mark.asyncio
    async def test_trigger_escalation_passes_context(self):
        """Verify conversation context is passed through to perform_escalation."""
        context = [
            {"role": "user", "content": "Necesito ayuda"},
            {"role": "assistant", "content": "Te ayudo"},
        ]
        mock_perform = AsyncMock(
            return_value=EscalationResult(success=True, steps_completed=["disable_bot"])
        )
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            await trigger_escalation(
                reason="manual_request",
                conversation_id="12345",
                customer_phone="+34612345678",
                conversation_context=context,
            )

        call_kwargs = mock_perform.call_args.kwargs
        assert call_kwargs["conversation_context"] == context

    @pytest.mark.asyncio
    async def test_trigger_escalation_returns_legacy_shape(self):
        """trigger_escalation always returns dict with chatwoot_disabled, notification_id, webhooks_triggered."""
        mock_result = EscalationResult(
            success=True,
            escalation_id=None,
            steps_completed=["disable_bot"],
        )
        with patch(
            "agent.services.escalation_service.perform_escalation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await trigger_escalation(
                reason="manual_request",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        assert "chatwoot_disabled" in result
        assert "notification_id" in result
        assert "webhooks_triggered" in result


# ============================================================================
# Test Different Escalation Reasons (via trigger_escalation wrapper)
# ============================================================================


class TestEscalationReasons:
    """Test escalation with different predefined reasons forwarded through wrapper."""

    @pytest.mark.asyncio
    async def test_medical_consultation_escalation(self):
        """Test escalation for medical consultation passes reason to perform_escalation."""
        mock_perform = AsyncMock(
            return_value=EscalationResult(success=True, steps_completed=["disable_bot"])
        )
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            await trigger_escalation(
                reason="medical_consultation",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        call_kwargs = mock_perform.call_args.kwargs
        assert call_kwargs["reason"] == "medical_consultation"

    @pytest.mark.asyncio
    async def test_auto_escalation_reason(self):
        """Test auto-escalation reason is forwarded."""
        mock_perform = AsyncMock(
            return_value=EscalationResult(success=True, steps_completed=["disable_bot"])
        )
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            await trigger_escalation(
                reason="auto_escalation",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        call_kwargs = mock_perform.call_args.kwargs
        assert call_kwargs["reason"] == "auto_escalation"

    @pytest.mark.asyncio
    async def test_technical_error_escalation(self):
        """Test technical error reason is forwarded."""
        mock_perform = AsyncMock(
            return_value=EscalationResult(success=True, steps_completed=["disable_bot"])
        )
        with patch("agent.services.escalation_service.perform_escalation", mock_perform):
            await trigger_escalation(
                reason="technical_error",
                conversation_id="12345",
                customer_phone="+34612345678",
            )

        call_kwargs = mock_perform.call_args.kwargs
        assert call_kwargs["reason"] == "technical_error"


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    @pytest.mark.asyncio
    async def test_empty_conversation_id(self):
        """Test escalation with empty conversation ID."""
        with patch("shared.chatwoot_client.ChatwootClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.update_conversation_attributes.side_effect = ValueError("invalid literal")
            mock_client_class.return_value = mock_client

            result = await disable_bot_in_chatwoot("")

            # Should handle gracefully
            assert result is False

    @pytest.mark.asyncio
    async def test_empty_customer_phone(self):
        """Test notification with empty customer phone."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            result = await create_escalation_notification(
                reason="manual_request",
                customer_phone="",
                conversation_id="12345",
            )

            # Should still create notification
            assert result is not None

    @pytest.mark.asyncio
    async def test_empty_conversation_context(self):
        """Test notification with empty context list."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        captured_notification = None

        def capture_notification(n):
            nonlocal captured_notification
            captured_notification = n

        mock_session.add = capture_notification

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
                conversation_context=[],  # Empty list
            )

            # Should not include context section
            assert "Contexto reciente" not in captured_notification.message

    @pytest.mark.asyncio
    async def test_special_characters_in_context(self):
        """Test notification handles special characters in context."""
        notification_id = uuid4()

        mock_customer_result = MagicMock()
        mock_customer_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_customer_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(side_effect=lambda n: setattr(n, "id", notification_id))

        with patch("agent.services.escalation_service.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            context = [
                {"role": "user", "content": "¿Puedo reservar? 💕🌸"},
                {"role": "assistant", "content": "¡Claro! €100"},
            ]

            result = await create_escalation_notification(
                reason="manual_request",
                customer_phone="+34612345678",
                conversation_id="12345",
                conversation_context=context,
            )

            # Should handle emojis and special chars
            assert result is not None


# ============================================================================
# Test perform_escalation — 5-step pipeline
# ============================================================================


class TestPerformEscalation:
    """Tests for perform_escalation() — the central 5-step escalation pipeline."""

    @pytest.mark.asyncio
    async def test_perform_escalation_all_steps(self):
        """All 5 steps execute successfully when everything works."""
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock(return_value={"success": True})
        mock_client.add_conversation_labels = AsyncMock(return_value=True)
        mock_client.add_private_note = AsyncMock(return_value=True)
        mock_client.assign_to_team = AsyncMock(return_value=True)

        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=None)
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session", return_value=mock_db_session
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+5491100000000",
                reason="manual_request",
                source="manual",
            )

        assert result.success is True
        assert "disable_bot" in result.steps_completed
        mock_client.update_conversation_attributes.assert_called_once()

    @pytest.mark.asyncio
    async def test_perform_escalation_duplicate_prevented(self):
        """Returns duplicate_prevented=True when a recent escalation exists in the DB."""
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock(return_value={"success": True})

        existing_escalation = MagicMock()
        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=None)
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_escalation))
        )

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session", return_value=mock_db_session
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+5491100000000",
                reason="manual_request",
                source="manual",
            )

        assert result.duplicate_prevented is True

    @pytest.mark.asyncio
    async def test_perform_escalation_s1_failure_sets_success_false(self):
        """S1 (disable_bot) failure marks success=False but S2-S5 still attempted."""
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock(
            side_effect=Exception("Chatwoot down")
        )
        mock_client.add_conversation_labels = AsyncMock(return_value=True)
        mock_client.add_private_note = AsyncMock(return_value=True)
        mock_client.assign_to_team = AsyncMock(return_value=True)

        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=None)
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session", return_value=mock_db_session
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+5491100000000",
                reason="manual_request",
                source="manual",
            )

        assert result.success is False
        assert "disable_bot" in result.steps_failed

    @pytest.mark.asyncio
    async def test_perform_escalation_noncritical_failure_keeps_success_true(self):
        """Non-critical step (private_note) failure keeps success=True."""
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock(return_value={"success": True})
        mock_client.add_conversation_labels = AsyncMock(return_value=True)
        mock_client.add_private_note = AsyncMock(side_effect=Exception("note failed"))
        mock_client.assign_to_team = AsyncMock(return_value=True)

        mock_db_session = AsyncMock()
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=None)
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_db_session.add = MagicMock()
        mock_db_session.commit = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session", return_value=mock_db_session
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+5491100000000",
                reason="manual_request",
                source="manual",
            )

        assert result.success is True
        assert "private_note" in result.steps_failed

    @pytest.mark.asyncio
    async def test_perform_escalation_dedupe_failopen(self):
        """DB error during dedupe check is fail-open — escalation proceeds."""
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock(return_value={"success": True})
        mock_client.add_conversation_labels = AsyncMock(return_value=True)
        mock_client.add_private_note = AsyncMock(return_value=True)
        mock_client.assign_to_team = AsyncMock(return_value=True)

        # First call raises (dedupe check), subsequent calls succeed (S5 db_record)
        call_count = 0

        async def mock_session_cm():
            nonlocal call_count
            call_count += 1
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            if call_count == 1:
                # First context manager: dedupe check fails
                session.execute = AsyncMock(side_effect=Exception("DB unreachable"))
            else:
                # Second context manager: S5 DB record succeeds
                session.execute = AsyncMock(
                    return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
                )
                session.add = MagicMock()
                session.commit = AsyncMock()
            return session

        class FakeSessionCtx:
            async def __aenter__(self):
                return await mock_session_cm()

            async def __aexit__(self, *args):
                return None

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session",
                side_effect=lambda: FakeSessionCtx(),
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+5491100000000",
                reason="manual_request",
                source="manual",
            )

        assert result.duplicate_prevented is False
        assert result.success is True
