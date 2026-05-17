"""Unit tests for shared/email_service.py — EmailService."""

import smtplib
from decimal import Decimal
from unittest.mock import MagicMock, patch

from shared.email_service import EmailService

# =============================================================================
# Helpers
# =============================================================================


def _make_settings(smtp_host: str = "", smtp_user: str = "", smtp_port: int = 587):
    """Return a mock Settings object with SMTP fields."""
    s = MagicMock()
    s.SMTP_HOST = smtp_host
    s.SMTP_USER = smtp_user
    s.SMTP_PORT = smtp_port
    s.SMTP_PASSWORD = "secret"
    s.SMTP_FROM = ""
    return s


# =============================================================================
# is_configured
# =============================================================================


class TestIsConfigured:
    """Tests for EmailService.is_configured()."""

    def test_is_configured_false_when_no_smtp_host(self):
        """GIVEN SMTP_HOST is empty, WHEN is_configured called, THEN returns False."""
        with patch("shared.email_service.get_settings", return_value=_make_settings(smtp_host="")):
            service = EmailService()
            assert service.is_configured() is False

    def test_is_configured_false_when_no_smtp_user(self):
        """GIVEN SMTP_USER is empty (host set), WHEN is_configured called, THEN returns False."""
        with patch(
            "shared.email_service.get_settings",
            return_value=_make_settings(smtp_host="smtp.example.com", smtp_user=""),
        ):
            service = EmailService()
            assert service.is_configured() is False

    def test_is_configured_true_when_configured(self):
        """GIVEN both SMTP_HOST and SMTP_USER are set, WHEN is_configured, THEN returns True."""
        with patch(
            "shared.email_service.get_settings",
            return_value=_make_settings(
                smtp_host="smtp.example.com", smtp_user="user@example.com"
            ),
        ):
            service = EmailService()
            assert service.is_configured() is True


# =============================================================================
# send_invoice_email
# =============================================================================


class TestSendInvoiceEmail:
    """Tests for EmailService.send_invoice_email()."""

    async def test_send_invoice_email_skips_when_not_configured(self):
        """GIVEN SMTP not configured, WHEN send_invoice_email called, THEN returns False, no SMTP call."""
        with patch(
            "shared.email_service.get_settings", return_value=_make_settings(smtp_host="")
        ):
            with patch("smtplib.SMTP") as mock_smtp:
                service = EmailService()
                result = await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-2026-03",
                    period_label="Marzo 2026",
                    total_eur=Decimal("150.00"),
                    pdf_path="/tmp/nonexistent.pdf",
                )

        assert result is False
        mock_smtp.assert_not_called()

    async def test_send_invoice_email_sends_with_attachment(self, tmp_path):
        """GIVEN SMTP configured and PDF exists, WHEN send_invoice_email, THEN sends with attachment."""
        # Create a fake PDF file
        pdf_file = tmp_path / "INV-2026-03.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = "billing@salon.es"

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                result = await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-2026-03",
                    period_label="Marzo 2026",
                    total_eur=Decimal("150.00"),
                    pdf_path=str(pdf_file),
                )

        assert result is True
        mock_smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=30)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_smtp_instance.send_message.assert_called_once()

        # Verify the sent message contains expected data
        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "owner@salon.es"
        assert "INV-2026-03" in sent_msg["Subject"]

    async def test_send_invoice_email_sends_without_attachment_when_pdf_missing(self):
        """GIVEN PDF does not exist, WHEN send_invoice_email, THEN sends without attachment (no crash)."""
        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = ""

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                result = await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-2026-02",
                    period_label="Febrero 2026",
                    total_eur=Decimal("120.00"),
                    pdf_path="/tmp/does_not_exist_at_all.pdf",
                )

        assert result is True
        mock_smtp_instance.send_message.assert_called_once()

    async def test_send_invoice_email_uses_smtp_from_when_set(self, tmp_path):
        """GIVEN SMTP_FROM is set, WHEN sending, THEN From header uses SMTP_FROM (not SMTP_USER)."""
        pdf_file = tmp_path / "INV.pdf"
        pdf_file.write_bytes(b"fake")

        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = "noreply@salon.es"

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-001",
                    period_label="Enero 2026",
                    total_eur=Decimal("100.00"),
                    pdf_path=str(pdf_file),
                )

        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["From"] == "noreply@salon.es"

    async def test_send_invoice_email_uses_smtp_user_as_from_when_smtp_from_empty(self, tmp_path):
        """GIVEN SMTP_FROM is empty, WHEN sending, THEN From header falls back to SMTP_USER."""
        pdf_file = tmp_path / "INV.pdf"
        pdf_file.write_bytes(b"fake")

        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = ""

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-001",
                    period_label="Enero 2026",
                    total_eur=Decimal("100.00"),
                    pdf_path=str(pdf_file),
                )

        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["From"] == "user@example.com"

    async def test_send_invoice_email_returns_false_on_smtp_error(self):
        """GIVEN SMTP raises during send, WHEN send_invoice_email, THEN returns False without raising."""
        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = ""

        def _raise_on_enter(*args, **kwargs):
            raise smtplib.SMTPConnectError(421, b"Service unavailable")

        mock_smtp_class = MagicMock(side_effect=_raise_on_enter)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                result = await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-2026-03",
                    period_label="Marzo 2026",
                    total_eur=Decimal("150.00"),
                    pdf_path="/tmp/nonexistent.pdf",
                )

        assert result is False

    async def test_send_invoice_email_returns_false_on_login_error(self):
        """GIVEN SMTP login raises, WHEN send_invoice_email, THEN returns False without raising."""
        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = ""

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.starttls = MagicMock()
        mock_smtp_instance.login = MagicMock(
            side_effect=smtplib.SMTPAuthenticationError(535, b"Auth failed")
        )

        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                result = await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="INV-2026-03",
                    period_label="Marzo 2026",
                    total_eur=Decimal("150.00"),
                    pdf_path="/tmp/nonexistent.pdf",
                )

        assert result is False


# =============================================================================
# T9-email — None pdf_path guard (TDD RED → T1 implementation makes GREEN)
# =============================================================================


class TestSendInvoiceEmailNonePdfPath:
    """Tests covering the pdf_path=None guard introduced in billing-wip-completion."""

    async def test_send_invoice_email_accepts_none_pdf_path(self):
        """
        GIVEN SMTP is not configured (safe path — avoids real SMTP)
        AND pdf_path=None
        WHEN send_invoice_email is called
        THEN no TypeError (Path(None)) is raised
        AND the call returns False (SMTP unconfigured)
        """
        with patch(
            "shared.email_service.get_settings",
            return_value=_make_settings(smtp_host=""),  # not configured
        ):
            service = EmailService()
            # Must NOT raise — pre-fix would crash with TypeError: argument should be str
            result = await service.send_invoice_email(
                to="owner@salon.es",
                invoice_number="ATR-2026-03-001",
                period_label="Marzo 2026",
                total_eur=Decimal("100.00"),
                pdf_path=None,
            )

        # SMTP not configured → returns False (not a crash)
        assert result is False

    async def test_send_invoice_email_none_path_still_sends_with_smtp_configured(self):
        """
        GIVEN SMTP is configured
        AND pdf_path=None
        WHEN send_invoice_email is called
        THEN email is sent without a PDF attachment (no crash)
        AND method returns True
        """
        settings = _make_settings(smtp_host="smtp.example.com", smtp_user="user@example.com")
        settings.SMTP_FROM = ""

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch("shared.email_service.get_settings", return_value=settings):
            with patch("smtplib.SMTP", mock_smtp_class):
                service = EmailService()
                result = await service.send_invoice_email(
                    to="owner@salon.es",
                    invoice_number="ATR-2026-03-001",
                    period_label="Marzo 2026",
                    total_eur=Decimal("100.00"),
                    pdf_path=None,  # <— the fix
                )

        assert result is True
        # Email was sent even without an attachment
        mock_smtp_instance.send_message.assert_called_once()
