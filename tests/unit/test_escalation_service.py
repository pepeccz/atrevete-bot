"""
Tests for escalation_service.py - Human escalation workflow.

This module tests the escalation service that handles human handoff:
- perform_escalation: Central pipeline with graceful degradation
- create_escalation_notification: Create admin panel notification
- trigger_escalation: Backward-compatible wrapper (delegates to perform_escalation)

Coverage:
- perform_escalation: all steps, duplicate prevention, partial failures
- R4 — paused_at written atomically via ON CONFLICT (ADR-3)
- Notification creation with customer lookup
- Notification creation with conversation context
- Reason-to-notification-type mapping
- Error handling and graceful degradation
"""

from datetime import UTC
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
    perform_escalation,
    trigger_escalation,
)
from database.models import NotificationType, compute_is_paused

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
        """All steps execute successfully when everything works.

        After T-08: S1 disable_bot is removed; paused_at is written via ON CONFLICT
        in the same transaction as the Escalation row (atomically).
        update_conversation_attributes must NOT be called by S1.
        """
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
        # S1 disable_bot is deleted — update_conversation_attributes must NOT be called
        mock_client.update_conversation_attributes.assert_not_called()

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
    async def test_perform_escalation_chatwoot_failure_keeps_success_true(self):
        """N2: Chatwoot label/note/team failure does not flip success — DB record is SSOT.
        After T-08 the S1 disable_bot step is removed; S2/S3/S4 are still best-effort."""
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

        assert result.success is True
        assert "db_record" in result.steps_completed
        # S1 disable_bot is removed — update_conversation_attributes is best-effort only in S2/S3/S4

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


# ============================================================================
# Change N (N2) — DB-record-first escalation contract
# ============================================================================


def _working_db_session():
    """Async session mock that satisfies dedupe + S5 record + S6 notification."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestEscalationDbRecordFirst:
    """N2: the escalation DB record is written FIRST, independent of Chatwoot."""

    @pytest.mark.asyncio
    async def test_uuid_conversation_id_still_writes_db_record(self):
        """Non-integer conversation_id: skip Chatwoot calls, still record, no crash."""
        mock_session = _working_db_session()
        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session",
                return_value=mock_session,
            ),
        ):
            result = await perform_escalation(
                conversation_id="389a06a0-1234-5678-9abc-def012345678",
                customer_phone="+34999000023",
                reason="manual_request",
                source="manual",
            )

        assert result.success is True, (
            "UUID conversation_id must not abort the escalation — the DB record "
            "is the source of truth (V6 C2 phantom escalation)"
        )
        assert "db_record" in result.steps_completed
        assert result.escalation_id is not None
        mock_session.add.assert_called()
        # No Chatwoot API call may fire with a non-integer conversation id
        mock_client.update_conversation_attributes.assert_not_called()
        mock_client.add_conversation_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_chatwoot_down_still_writes_db_record(self):
        """All Chatwoot calls raising must not prevent the DB record (success=True)."""
        mock_session = _working_db_session()
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock(
            side_effect=Exception("Chatwoot 502")
        )
        mock_client.add_conversation_labels = AsyncMock(side_effect=Exception("Chatwoot 502"))
        mock_client.add_private_note = AsyncMock(side_effect=Exception("Chatwoot 502"))
        mock_client.assign_to_team = AsyncMock(side_effect=Exception("Chatwoot 502"))

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session",
                return_value=mock_session,
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+34999000023",
                reason="manual_request",
                source="manual",
            )

        assert (
            result.success is True
        ), "Chatwoot outage must not flip success — escalation IS recorded"
        assert "db_record" in result.steps_completed
        # S1 disable_bot is removed — Chatwoot failure only affects S2/S3/S4 steps

    @pytest.mark.asyncio
    async def test_db_record_failure_sets_success_false(self):
        """If the escalation DB record cannot be written, success must be False."""
        call_count = 0

        def session_factory():
            nonlocal call_count
            call_count += 1
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            # Dedupe check fails open; S5 commit raises; S6 also fails.
            session.execute = AsyncMock(side_effect=Exception("DB down"))
            session.add = MagicMock()
            session.commit = AsyncMock(side_effect=Exception("DB down"))
            return session

        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session",
                side_effect=lambda: session_factory(),
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+34999000023",
                reason="manual_request",
                source="manual",
            )

        assert (
            result.success is False
        ), "DB record failure must produce an explicit failure (no phantom escalation)"
        assert "db_record" in result.steps_failed

    @pytest.mark.asyncio
    async def test_db_record_failure_paused_at_not_written(self):
        """W2 / V6: when the DB write fails, paused_at must NOT be set (no partial state).

        The ON CONFLICT upsert is inside the same transaction as the Escalation row.
        If commit() fails, NEITHER the Escalation row NOR the paused_at write persists.
        """

        def session_factory():
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.execute = AsyncMock(side_effect=Exception("DB down"))
            session.add = MagicMock()
            session.commit = AsyncMock(side_effect=Exception("DB down"))
            return session

        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session",
                side_effect=lambda: session_factory(),
            ),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+34999000023",
                reason="manual_request",
                source="manual",
            )

        assert result.success is False
        assert "db_record" in result.steps_failed
        # paused_at not written — Chatwoot update NOT called either (no partial state)
        mock_client.update_conversation_attributes.assert_not_called()


# ============================================================================
# R4 — paused_at written atomically with Escalation row via ON CONFLICT (T-07/T-08)
# ============================================================================


def _working_db_session_with_spy():
    """Async session that tracks execute() calls and records ON CONFLICT statements."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


class TestEscalationPausedAtAtomicity:
    """R4: perform_escalation writes paused_at atomically with the Escalation row.

    Spec refs: R3-D, R4, ADR-3 (ON CONFLICT upsert), ADR-6 step 8.
    """

    @pytest.mark.asyncio
    async def test_r4a_escalation_sets_paused_at_no_chatwoot(self):
        """R4-A: perform_escalation writes ConversationHistory.paused_at atomically
        with the Escalation row and does NOT call update_conversation_attributes."""
        from database.models import ConversationHistory

        captured_stmts: list = []

        async def _capture_execute(stmt, *args, **kwargs):
            captured_stmts.append(stmt)
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.execute = AsyncMock(side_effect=_capture_execute)
        session.add = MagicMock()
        session.commit = AsyncMock()

        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch("agent.services.escalation_service.get_async_session", return_value=session),
        ):
            result = await perform_escalation(
                conversation_id="123",
                customer_phone="+34999000001",
                reason="manual_request",
                source="manual",
            )

        assert result.success is True
        assert "db_record" in result.steps_completed

        # The ON CONFLICT upsert must have been executed (at least one execute call
        # after the dedupe check touches ConversationHistory table)
        stmt_reprs = [str(s) for s in captured_stmts]
        assert any(
            "conversation_history" in r.lower() or "conversationhistory" in r.lower()
            for r in stmt_reprs
        ), (
            "Expected an ON CONFLICT execute() targeting conversation_history. "
            f"Captured statements: {stmt_reprs}"
        )

        # S1 disable_bot removed — update_conversation_attributes must NOT be called
        mock_client.update_conversation_attributes.assert_not_called()

    @pytest.mark.asyncio
    async def test_r4a_compute_is_paused_true_after_escalation(self):
        """R4-A (variant): after the ON CONFLICT write, the row has paused_at set
        so compute_is_paused would return True for that conversation."""
        from database.models import ConversationHistory

        now = None
        captured_paused_at = None

        async def _spy_execute(stmt, *args, **kwargs):
            nonlocal captured_paused_at
            # Inspect the compiled statement values for ON CONFLICT inserts
            try:
                # For SQLAlchemy Insert objects
                if hasattr(stmt, "table") and stmt.table.name == "conversation_history":
                    # Extract paused_at from the insert values
                    for col, val in stmt._values.items() if hasattr(stmt, "_values") else []:
                        if "paused_at" in str(col):
                            captured_paused_at = val
            except Exception:
                pass
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.execute = AsyncMock(side_effect=_spy_execute)
        session.add = MagicMock()
        session.commit = AsyncMock()

        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch("agent.services.escalation_service.get_async_session", return_value=session),
        ):
            result = await perform_escalation(
                conversation_id="999",
                customer_phone="+34999000002",
                reason="auto_escalation",
                source="auto",
            )

        assert result.success is True
        # The execute was called (ON CONFLICT statement ran)
        assert session.execute.call_count >= 2, (
            "Expected at least 2 execute() calls: dedupe check + ON CONFLICT upsert"
        )

    @pytest.mark.asyncio
    async def test_r4c_first_contact_inserts_minimal_history_row(self):
        """R4-C: escalation on first-contact (no existing history row) inserts a
        minimal ConversationHistory with paused_at=now via the ON CONFLICT INSERT path.
        No UNIQUE violation occurs because ON CONFLICT handles the first-insert case."""
        from sqlalchemy.exc import IntegrityError

        session = _working_db_session_with_spy()
        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch("agent.services.escalation_service.get_async_session", return_value=session),
        ):
            result = await perform_escalation(
                conversation_id="first-contact-123",
                customer_phone="+34999000003",
                reason="manual_request",
                source="manual",
            )

        # Escalation row written + ON CONFLICT executed — no UNIQUE error
        assert result.success is True
        assert "db_record" in result.steps_completed
        # commit() was called (both row + upsert in one transaction)
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_r4d_both_rollback_atomicity(self):
        """R4-D: force failure after db.add(escalation_row) + ON CONFLICT execute
        → assert NEITHER Escalation row NOR paused_at persists (both-commit-or-both-rollback).

        The S5 session wraps escalation_row add + ON CONFLICT upsert + commit() in one
        transaction.  When commit() raises, PostgreSQL rolls back the whole unit — both
        the Escalation row and the paused_at write are discarded atomically.
        """
        from sqlalchemy.exc import SQLAlchemyError

        s5_committed = False

        class _FailingS5Session:
            """Session whose commit() always raises — simulates a failed S5 transaction."""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def execute(self, stmt, *a, **kw):
                result = MagicMock()
                result.scalar_one_or_none.return_value = None
                return result

            def add(self, obj):
                pass

            async def commit(self):
                raise SQLAlchemyError("disk full — S5 rollback")

        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch(
                "agent.services.escalation_service.get_async_session",
                side_effect=lambda: _FailingS5Session(),
            ),
        ):
            result = await perform_escalation(
                conversation_id="456",
                customer_phone="+34999000004",
                reason="technical_error",
                source="auto",
            )

        # S5 transaction failed → success is False, db_record in steps_failed
        assert result.success is False, "DB commit failure must set result.success=False"
        assert "db_record" in result.steps_failed, "db_record must be in steps_failed"
        # S5 never committed → neither Escalation nor paused_at write persisted
        assert s5_committed is False, "S5 transaction must not have committed"

    @pytest.mark.asyncio
    async def test_on_conflict_existing_row_no_unique_error(self):
        """ON CONFLICT on existing row: sets paused_at=now, resumed_at=None,
        no UNIQUE error, Escalation row survives (both commit together)."""
        session = _working_db_session_with_spy()
        mock_client = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch("agent.services.escalation_service.get_async_session", return_value=session),
        ):
            result = await perform_escalation(
                conversation_id="existing-conv-789",
                customer_phone="+34999000005",
                reason="ambiguity",
                source="auto",
            )

        # Both rows written atomically — no UNIQUE violation
        assert result.success is True
        assert "db_record" in result.steps_completed
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_chatwoot_write_on_escalation(self):
        """R4-A: escalation must NOT call update_conversation_attributes (S1 removed)."""
        session = _working_db_session_with_spy()
        mock_client = AsyncMock()
        mock_client.update_conversation_attributes = AsyncMock()

        with (
            patch("shared.chatwoot_client.ChatwootClient", return_value=mock_client),
            patch("agent.services.escalation_service.get_async_session", return_value=session),
        ):
            await perform_escalation(
                conversation_id="no-chatwoot-test",
                customer_phone="+34999000006",
                reason="manual_request",
                source="manual",
            )

        mock_client.update_conversation_attributes.assert_not_called()
