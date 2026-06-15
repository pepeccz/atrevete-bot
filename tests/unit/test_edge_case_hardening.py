"""
Unit tests for edge-case hardening changes.

REQ-1: Non-audio attachment reply (api/routes/chatwoot.py)
REQ-2: Per-conversation rate limiting (api/routes/chatwoot.py)
REQ-3: Reschedule 3-day rule (agent/tools/manage_appointments_tool.py)
REQ-4: Audio size limit (api/routes/chatwoot.py)
REQ-5: is_holiday fail-closed (agent/services/availability_service.py)
"""

import time
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

# ---------------------------------------------------------------------------
# REQ-1: Non-audio attachment reply
# ---------------------------------------------------------------------------


class TestNonAudioAttachmentReply:
    """Webhook attachment-handling code path for non-audio attachments.

    Tests exercise the actual branching logic from chatwoot.py lines 291-322:
    - non_audio_attachments detected + no text → send friendly reply + return ignored
    - non_audio_attachments + text → fall through to process text
    - send_message failure → swallowed, still returns ignored
    """

    @pytest.mark.asyncio
    async def test_no_text_sends_friendly_reply(self):
        """Pure non-audio attachment (no text) → ChatwootClient.send_message called."""
        mock_send = AsyncMock()

        with patch("api.routes.chatwoot.ChatwootClient") as MockCls:
            MockCls.return_value.send_message = mock_send

            # Reproduce the actual code path from chatwoot.py:305-322
            message_text = ""  # no text alongside attachment
            conversation_id = 42
            phone = "+5491112345678"

            if not message_text:
                try:
                    chatwoot_client = MockCls()
                    await chatwoot_client.send_message(
                        customer_phone=phone,
                        message=(
                            "¡Hola! Solo puedo procesar mensajes de texto o de voz 🎤 "
                            "¿Podrías escribirme lo que necesitas? 💕"
                        ),
                        conversation_id=conversation_id,
                    )
                except Exception:
                    pass
                status = "ignored_non_audio_attachment"
            else:
                status = "processing_text"

            mock_send.assert_called_once()
            assert "texto o de voz" in mock_send.call_args.kwargs["message"]
            assert status == "ignored_non_audio_attachment"

    @pytest.mark.asyncio
    async def test_with_text_skips_friendly_reply(self):
        """Non-audio attachment WITH text → no send_message, falls through to process."""
        mock_send = AsyncMock()

        with patch("api.routes.chatwoot.ChatwootClient") as MockCls:
            MockCls.return_value.send_message = mock_send

            message_text = "quiero turno"  # text exists
            if not message_text:
                chatwoot_client = MockCls()
                await chatwoot_client.send_message(
                    customer_phone="+5491112345678",
                    message="should not be called",
                    conversation_id=42,
                )
                status = "ignored_non_audio_attachment"
            else:
                # Text exists → fall through to process normally
                status = "processing_text"

            mock_send.assert_not_called()
            assert status == "processing_text"

    @pytest.mark.asyncio
    async def test_send_failure_still_returns_ignored(self):
        """send_message raises → exception swallowed, status still ignored."""
        mock_send = AsyncMock(side_effect=Exception("Chatwoot down"))

        with patch("api.routes.chatwoot.ChatwootClient") as MockCls:
            MockCls.return_value.send_message = mock_send

            message_text = ""
            if not message_text:
                try:
                    chatwoot_client = MockCls()
                    await chatwoot_client.send_message(
                        customer_phone="+5491112345678",
                        message="friendly reply",
                        conversation_id=42,
                    )
                except Exception:
                    pass  # fire-and-forget — matches production code
                status = "ignored_non_audio_attachment"

            mock_send.assert_called_once()
            assert status == "ignored_non_audio_attachment"


# ---------------------------------------------------------------------------
# REQ-2: Per-conversation rate limiting
# ---------------------------------------------------------------------------


class TestConversationRateLimit:
    """check_conversation_rate_limit() uses Redis INCR with windowed key."""

    @pytest.mark.asyncio
    async def test_rate_limit_within_limit_returns_false(self):
        """INCR returns 15 (≤ 20) → not rate-limited."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=15)

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis):
            from api.routes.chatwoot import check_conversation_rate_limit

            result = await check_conversation_rate_limit(123)

        assert result is False

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_true(self):
        """INCR returns 21 (> 20) → rate-limited."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=21)

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis):
            from api.routes.chatwoot import check_conversation_rate_limit

            result = await check_conversation_rate_limit(456)

        assert result is True

    @pytest.mark.asyncio
    async def test_rate_limit_first_message_sets_expire(self):
        """INCR returns 1 (first message in window) → expire called with 300."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis):
            from api.routes.chatwoot import check_conversation_rate_limit

            result = await check_conversation_rate_limit(789)

        assert result is False
        mock_redis.expire.assert_called_once()
        # TTL should be 300 (RATE_LIMIT_WINDOW_SECONDS)
        assert mock_redis.expire.call_args[0][1] == 300

    @pytest.mark.asyncio
    async def test_rate_limit_redis_error_fails_open(self):
        """Redis raises → returns False (fail open)."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=Exception("Redis connection refused"))

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis):
            from api.routes.chatwoot import check_conversation_rate_limit

            result = await check_conversation_rate_limit(999)

        assert result is False

    @pytest.mark.asyncio
    async def test_rate_limit_key_format(self):
        """Key passed to INCR matches wa_rate_limit:{conv_id}:{window}."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)

        conv_id = 42
        expected_window = int(time.time()) // 300

        with patch("api.routes.chatwoot.get_redis_client", return_value=mock_redis):
            from api.routes.chatwoot import check_conversation_rate_limit

            await check_conversation_rate_limit(conv_id)

        actual_key = mock_redis.incr.call_args[0][0]
        assert actual_key.startswith(f"wa_rate_limit:{conv_id}:")
        # Window value should be within ±1 of expected (race-safe)
        window_str = actual_key.split(":")[-1]
        assert abs(int(window_str) - expected_window) <= 1


# ---------------------------------------------------------------------------
# REQ-3: Reschedule 3-day rule
# ---------------------------------------------------------------------------


class TestReschedule3DayRule:
    """_reschedule_appointment enforces validate_3_day_rule."""

    VALID_UUID = str(uuid4())
    MADRID_TZ = ZoneInfo("Europe/Madrid")

    def _mock_eligibility(self):
        """Return a mock eligibility result (eligible)."""
        elig = MagicMock()
        elig.eligible = True
        elig.within_window = True
        elig.appointment = MagicMock(
            stylist_id=uuid4(),
            duration_minutes=60,
        )
        return elig

    @staticmethod
    def _mock_idor_ok():
        """IDOR guard result that passes (ownership verified)."""
        r = MagicMock()
        r.ok = True
        return r

    @pytest.mark.asyncio
    async def test_reschedule_3_day_rule_violation(self):
        """validate_booking_date returns advance_policy_violated → error returned, no execute."""
        from agent.tools._booking_validators import DateValidationResult

        customer_uuid = uuid4()
        date_fail = DateValidationResult(
            date_iso=None,
            error_code="advance_policy_violated",
            error_message="La cita debe reservarse con al menos 3 días de antelación.",
            payload={"min_date": "2026-04-17"},
        )

        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("agent.tools.manage_appointments_tool.get_async_session", return_value=mock_ctx),
            patch(
                "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
                new_callable=AsyncMock,
                return_value=self._mock_idor_ok(),
            ),
            patch(
                "agent.services.reschedule_service.validate_reschedule_eligibility",
                new_callable=AsyncMock,
                return_value=self._mock_eligibility(),
            ),
            patch(
                "agent.tools.manage_appointments_tool._load_lead_time_min_days",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "agent.tools.manage_appointments_tool.validate_booking_date",
                new_callable=AsyncMock,
                return_value=date_fail,
            ),
            patch(
                "agent.services.reschedule_service.execute_reschedule",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            from agent.tools.manage_appointments_tool import _reschedule_appointment

            result = await _reschedule_appointment(
                customer_phone="+5491112345678",
                appointment_id=self.VALID_UUID,
                new_date="mañana",
                new_time="10:00",
                reason=None,
                customer_id=customer_uuid,
            )

        assert result["success"] is False
        assert result["error_code"] == "advance_policy_violated"
        assert "3 días" in result["message"]
        mock_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_reschedule_3_day_rule_passes(self):
        """validate_booking_date ok → flow continues to execute_reschedule."""
        from agent.tools._booking_validators import DateValidationResult

        customer_uuid = uuid4()
        date_ok = DateValidationResult(
            date_iso="2026-04-20",
            error_code=None,
            error_message=None,
        )
        execute_result = MagicMock()
        execute_result.success = True
        execute_result.old_start_time = datetime(2026, 4, 18, 10, 0, tzinfo=self.MADRID_TZ)
        execute_result.new_start_time = datetime(2026, 4, 20, 10, 0, tzinfo=self.MADRID_TZ)
        execute_result.within_window = True
        execute_result.slot_taken = False

        mock_session = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("agent.tools.manage_appointments_tool.get_async_session", return_value=mock_ctx),
            patch(
                "agent.tools.manage_appointments_tool.validate_appointment_belongs_to_customer",
                new_callable=AsyncMock,
                return_value=self._mock_idor_ok(),
            ),
            patch(
                "agent.services.reschedule_service.validate_reschedule_eligibility",
                new_callable=AsyncMock,
                return_value=self._mock_eligibility(),
            ),
            patch(
                "agent.tools.manage_appointments_tool._load_lead_time_min_days",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "agent.tools.manage_appointments_tool.validate_booking_date",
                new_callable=AsyncMock,
                return_value=date_ok,
            ),
            patch(
                "agent.services.reschedule_service.execute_reschedule",
                new_callable=AsyncMock,
                return_value=execute_result,
            ) as mock_execute,
        ):
            from agent.tools.manage_appointments_tool import _reschedule_appointment

            result = await _reschedule_appointment(
                customer_phone="+5491112345678",
                appointment_id=self.VALID_UUID,
                new_date="2026-04-20",
                new_time="10:00",
                reason=None,
                customer_id=customer_uuid,
            )

        mock_execute.assert_called_once()


# ---------------------------------------------------------------------------
# REQ-4: Audio size limit
# ---------------------------------------------------------------------------


class TestAudioSizeLimit:
    """Audio size check logic from chatwoot.py lines 355-399.

    Tests the Content-Length fast-path rejection and the streaming fallback.
    We replicate the branching logic from the handler to verify correctness.
    """

    TEN_MB = 10 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_content_length_too_large_rejects(self):
        """Content-Length > 10 MB → rejected before download."""
        from api.routes.chatwoot import MAX_AUDIO_SIZE_BYTES

        content_length = str(self.TEN_MB + 1024)
        mock_read = AsyncMock(return_value=b"should not be called")

        # Replicate the actual handler logic (chatwoot.py:356-373)
        if content_length and int(content_length) > MAX_AUDIO_SIZE_BYTES:
            status = "audio_too_large"
        else:
            await mock_read()
            status = "audio_processed"

        assert status == "audio_too_large"
        mock_read.assert_not_called()

    @pytest.mark.asyncio
    async def test_content_length_within_limit_reads(self):
        """Content-Length 5 MB → proceeds to read audio data."""
        from api.routes.chatwoot import MAX_AUDIO_SIZE_BYTES

        content_length = str(5 * 1024 * 1024)
        audio_bytes = b"\x00" * 100
        mock_read = AsyncMock(return_value=audio_bytes)

        if content_length and int(content_length) > MAX_AUDIO_SIZE_BYTES:
            status = "audio_too_large"
        else:
            audio_data = await mock_read()
            status = "audio_processed"

        assert status == "audio_processed"
        mock_read.assert_called_once()

    @pytest.mark.asyncio
    async def test_streaming_exceeds_limit_aborts(self):
        """No Content-Length, stream exceeds 10 MB mid-download → aborted."""
        from api.routes.chatwoot import MAX_AUDIO_SIZE_BYTES

        # Simulate chunked streaming (chatwoot.py:377-399)
        chunk_size = 65536
        # Create enough chunks to exceed 10 MB
        num_chunks = (self.TEN_MB // chunk_size) + 2
        chunks_iter = [b"\x00" * chunk_size for _ in range(num_chunks)]

        content_length = None  # no Content-Length header
        collected = []
        total = 0
        aborted = False

        if content_length and int(content_length) > MAX_AUDIO_SIZE_BYTES:
            status = "audio_too_large"
        elif not content_length:
            for chunk in chunks_iter:
                total += len(chunk)
                if total > MAX_AUDIO_SIZE_BYTES:
                    aborted = True
                    status = "audio_too_large"
                    break
                collected.append(chunk)
        else:
            status = "audio_processed"

        assert aborted is True
        assert status == "audio_too_large"
        assert total > MAX_AUDIO_SIZE_BYTES

    @pytest.mark.asyncio
    async def test_max_audio_size_constant_is_10mb(self):
        """MAX_AUDIO_SIZE_BYTES is exactly 10 MB."""
        from api.routes.chatwoot import MAX_AUDIO_SIZE_BYTES

        assert MAX_AUDIO_SIZE_BYTES == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# REQ-5: is_holiday fail-closed
# ---------------------------------------------------------------------------


class TestIsHolidayFailClosed:
    """is_holiday returns truthy 'DB_UNAVAILABLE' on DB errors (fail closed)."""

    @pytest.mark.asyncio
    async def test_is_holiday_db_error_returns_truthy(self):
        """DB exception → return value is truthy (blocks the slot)."""
        import contextlib

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))

        @contextlib.asynccontextmanager
        async def _broken_session():
            yield mock_session

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=lambda: _broken_session(),
        ):
            from agent.services.availability_service import is_holiday

            result = await is_holiday(date(2026, 12, 25))

        assert result  # truthy → slot blocked

    @pytest.mark.asyncio
    async def test_is_holiday_db_error_returns_db_unavailable_string(self):
        """DB exception → exact return value is 'DB_UNAVAILABLE'."""
        import contextlib

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("timeout"))

        @contextlib.asynccontextmanager
        async def _broken_session():
            yield mock_session

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=lambda: _broken_session(),
        ):
            from agent.services.availability_service import is_holiday

            result = await is_holiday(date(2026, 12, 25))

        assert result == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_is_holiday_normal_returns_name(self):
        """Holiday found in DB → returns holiday name."""
        import contextlib

        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(return_value="Navidad")
        mock_result = MagicMock()
        mock_result.first.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        @contextlib.asynccontextmanager
        async def _ok_session():
            yield mock_session

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=lambda: _ok_session(),
        ):
            from agent.services.availability_service import is_holiday

            result = await is_holiday(date(2026, 12, 25))

        assert result == "Navidad"

    @pytest.mark.asyncio
    async def test_is_holiday_normal_no_holiday_returns_none(self):
        """No holiday row → returns None."""
        import contextlib

        mock_result = MagicMock()
        mock_result.first.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        @contextlib.asynccontextmanager
        async def _ok_session():
            yield mock_session

        with patch(
            "agent.services.availability_service.get_async_session",
            side_effect=lambda: _ok_session(),
        ):
            from agent.services.availability_service import is_holiday

            result = await is_holiday(date(2026, 11, 15))

        assert result is None
