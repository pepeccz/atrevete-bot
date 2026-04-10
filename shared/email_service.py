"""SMTP email service for invoice delivery. Gracefully degrades when not configured."""

import asyncio
import logging
import smtplib
from decimal import Decimal
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from shared.config import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    """SMTP email sender. Never raises — logs errors and returns False."""

    def is_configured(self) -> bool:
        """True if SMTP credentials are set."""
        settings = get_settings()
        return bool(settings.SMTP_HOST and settings.SMTP_USER)

    async def send_invoice_email(
        self,
        to: str,
        invoice_number: str,
        period_label: str,
        total_eur: Decimal,
        pdf_path: str,
    ) -> bool:
        """
        Send invoice notification with PDF attachment.

        Returns True if sent, False if skipped or failed.
        Never raises — errors are logged.
        """
        if not self.is_configured():
            logger.warning("SMTP not configured, skipping invoice email")
            return False

        settings = get_settings()

        try:
            msg = MIMEMultipart()
            msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
            msg["To"] = to
            msg["Subject"] = f"Factura {invoice_number} — Atrévete Bot"

            body = (
                f"Se ha generado la factura {invoice_number} "
                f"para el periodo {period_label}.\n\n"
                f"Total: {total_eur:.2f} €\n\n"
                f"Se adjunta el PDF de la factura.\n\n"
                f"— Atrévete Bot"
            )
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # Attach PDF if exists
            pdf_file = Path(pdf_path)
            if pdf_file.exists():
                with open(pdf_file, "rb") as f:
                    part = MIMEBase("application", "pdf")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{invoice_number}.pdf"',
                    )
                    msg.attach(part)
            else:
                logger.warning(
                    f"PDF not found at {pdf_path}, sending email without attachment"
                )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_sync, msg, settings)
            logger.info(f"Invoice email sent to {to} for {invoice_number}")
            return True

        except Exception as e:
            logger.warning(f"Failed to send invoice email to {to}: {e}")
            return False

    def _send_sync(self, msg: MIMEMultipart, settings) -> None:
        """Sync SMTP send — must be run in thread pool."""
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
