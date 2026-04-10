"""PDF invoice generation service using weasyprint."""

import asyncio
import logging
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from shared.config import get_settings

logger = logging.getLogger(__name__)

# Spanish month names
MONTH_NAMES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


class PdfService:
    """Invoice PDF generation via weasyprint + Jinja2."""

    def __init__(self):
        settings = get_settings()
        self.output_dir = Path(settings.INVOICES_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Jinja2 environment — templates dir is at project root /templates/
        self.jinja_env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=True,
        )

    async def generate_invoice_pdf(self, invoice) -> str:
        """Generate PDF for an invoice. Returns file path. Runs weasyprint in thread pool."""
        output_path = self.output_dir / f"{invoice.invoice_number}.pdf"
        html = self._render_html(invoice)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._write_pdf, html, str(output_path))
        logger.info(f"Generated PDF: {output_path}")
        return str(output_path)

    async def ensure_pdf_exists(self, invoice) -> str:
        """Return existing PDF path or regenerate if file is missing."""
        if invoice.pdf_path:
            path = Path(invoice.pdf_path)
            if path.exists():
                return str(path)
            logger.warning(f"PDF missing on disk for {invoice.invoice_number}, regenerating")
        return await self.generate_invoice_pdf(invoice)

    def _render_html(self, invoice) -> str:
        """Render Jinja2 template with invoice data."""
        settings = get_settings()

        # Token breakdown
        input_tokens = 0
        output_tokens = 0
        total_requests = 0
        if invoice.token_usage:
            input_tokens = invoice.token_usage.input_tokens
            output_tokens = invoice.token_usage.output_tokens
            total_requests = invoice.token_usage.total_requests

        input_price = settings.TOKEN_PRICE_INPUT
        output_price = settings.TOKEN_PRICE_OUTPUT
        input_cost = (Decimal(input_tokens) / Decimal("1000000")) * input_price
        output_cost = (Decimal(output_tokens) / Decimal("1000000")) * output_price

        period_label = f"{MONTH_NAMES.get(invoice.month, '')} {invoice.year}"

        template = self.jinja_env.get_template("invoice.html")
        return template.render(
            invoice=invoice,
            period_label=period_label,
            input_tokens=f"{input_tokens:,}".replace(",", "."),
            output_tokens=f"{output_tokens:,}".replace(",", "."),
            total_requests=f"{total_requests:,}".replace(",", "."),
            input_price=f"{input_price}",
            output_price=f"{output_price}",
            input_cost=f"{input_cost:.2f}",
            output_cost=f"{output_cost:.2f}",
            maintenance_amount=f"{invoice.maintenance_amount_eur:.2f}",
            token_amount=f"{invoice.token_amount_eur:.2f}",
            total_amount=f"{invoice.total_amount_eur:.2f}",
            issued_date=invoice.issued_at.strftime("%d/%m/%Y") if invoice.issued_at else "—",
            due_date=invoice.due_date.strftime("%d/%m/%Y") if invoice.due_date else "—",
            operator_email=settings.OPERATOR_EMAIL or "soporte@atrevetebot.com",
        )

    def _write_pdf(self, html: str, output_path: str) -> None:
        """Sync weasyprint call — must be run in thread pool executor."""
        from weasyprint import HTML

        HTML(string=html).write_pdf(output_path)
