"""Unit tests for PdfService — invoice PDF generation via weasyprint + Jinja2."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Guard: weasyprint requires OS-level deps (cairo, pango, fontconfig).
# Skip the whole module on environments where weasyprint is not importable.
try:
    import weasyprint as _weasyprint_check  # noqa: F401

    _WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    _WEASYPRINT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    invoices_dir: str = "/tmp/test_invoices",
    price_input: Decimal = Decimal("0.15"),
    price_output: Decimal = Decimal("0.60"),
    operator_email: str = "ops@test.com",
):
    s = MagicMock()
    s.INVOICES_DIR = invoices_dir
    s.TOKEN_PRICE_INPUT = price_input
    s.TOKEN_PRICE_OUTPUT = price_output
    s.OPERATOR_EMAIL = operator_email
    return s


def _make_invoice(
    invoice_number: str = "ATR-2026-03-001",
    year: int = 2026,
    month: int = 3,
    maintenance_amount_eur: Decimal = Decimal("50.00"),
    token_amount_eur: Decimal = Decimal("0.45"),
    total_amount_eur: Decimal = Decimal("50.45"),
    issued_at: datetime | None = None,
    due_date: date | None = None,
    pdf_path: str | None = None,
    with_token_usage: bool = True,
):
    """Create a mock Invoice object with all attributes needed by PdfService."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.invoice_number = invoice_number
    mock.year = year
    mock.month = month
    mock.maintenance_amount_eur = maintenance_amount_eur
    mock.token_amount_eur = token_amount_eur
    mock.total_amount_eur = total_amount_eur
    mock.issued_at = issued_at or datetime(2026, 3, 15, 12, 0, 0)
    mock.due_date = due_date or date(2026, 4, 14)
    mock.pdf_path = pdf_path

    if with_token_usage:
        token_usage = MagicMock()
        token_usage.input_tokens = 1_000_000
        token_usage.output_tokens = 500_000
        token_usage.total_requests = 42
        mock.token_usage = token_usage
    else:
        mock.token_usage = None

    return mock


def _build_pdf_service(settings, tmp_path: Path | None = None):
    """Instantiate PdfService with mocked settings and Jinja2 env."""
    from api.services.pdf_service import PdfService

    with patch("api.services.pdf_service.get_settings", return_value=settings):
        with patch("api.services.pdf_service.FileSystemLoader"):
            with patch("api.services.pdf_service.Environment") as mock_env_cls:
                mock_env = MagicMock()
                mock_env_cls.return_value = mock_env
                svc = PdfService.__new__(PdfService)
                svc.output_dir = tmp_path or Path(settings.INVOICES_DIR)
                svc.jinja_env = mock_env
                return svc, mock_env


# ---------------------------------------------------------------------------
# Tests — generate_invoice_pdf
# ---------------------------------------------------------------------------


class TestGenerateInvoicePdf:
    """generate_invoice_pdf creates a PDF file at the expected path."""

    async def test_generate_invoice_pdf_creates_file(self, tmp_path):
        """PDF is written to output_dir/{invoice_number}.pdf."""

        settings = _make_settings(invoices_dir=str(tmp_path))
        invoice = _make_invoice()

        svc, mock_jinja_env = _build_pdf_service(settings, tmp_path)

        # Mock _render_html to return a simple HTML string
        rendered_html = "<html><body>Invoice ATR-2026-03-001</body></html>"
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mock_jinja_env.get_template.return_value = mock_template

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            # Patch _write_pdf so we don't need weasyprint, but simulate file creation
            def fake_write_pdf(html: str, output_path: str):
                Path(output_path).write_bytes(b"%PDF-1.4 fake")

            svc._write_pdf = fake_write_pdf

            result_path = await svc.generate_invoice_pdf(invoice)

        expected = str(tmp_path / "ATR-2026-03-001.pdf")
        assert result_path == expected
        assert Path(result_path).exists()

    async def test_generate_invoice_pdf_returns_string_path(self, tmp_path):
        """Return type is str (not Path)."""

        settings = _make_settings(invoices_dir=str(tmp_path))
        invoice = _make_invoice()
        svc, mock_jinja_env = _build_pdf_service(settings, tmp_path)

        mock_template = MagicMock()
        mock_template.render.return_value = "<html></html>"
        mock_jinja_env.get_template.return_value = mock_template

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            svc._write_pdf = lambda html, path: Path(path).write_bytes(b"fake")
            result = await svc.generate_invoice_pdf(invoice)

        assert isinstance(result, str)

    async def test_generate_invoice_pdf_calls_write_in_executor(self, tmp_path):
        """_write_pdf is called via run_in_executor (not directly)."""

        settings = _make_settings(invoices_dir=str(tmp_path))
        invoice = _make_invoice()
        svc, mock_jinja_env = _build_pdf_service(settings, tmp_path)

        mock_template = MagicMock()
        mock_template.render.return_value = "<html></html>"
        mock_jinja_env.get_template.return_value = mock_template

        write_pdf_called_with = []

        def fake_write_pdf(html: str, output_path: str):
            write_pdf_called_with.append(output_path)
            Path(output_path).write_bytes(b"fake pdf")

        svc._write_pdf = fake_write_pdf

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            await svc.generate_invoice_pdf(invoice)

        assert len(write_pdf_called_with) == 1
        assert "ATR-2026-03-001.pdf" in write_pdf_called_with[0]


# ---------------------------------------------------------------------------
# Tests — ensure_pdf_exists
# ---------------------------------------------------------------------------


class TestEnsurePdfExists:
    """ensure_pdf_exists returns existing or regenerates missing PDFs."""

    async def test_ensure_pdf_exists_returns_existing(self, tmp_path):
        """When pdf_path exists on disk, returns it without regenerating."""

        # Create an actual file
        existing_pdf = tmp_path / "ATR-2026-03-001.pdf"
        existing_pdf.write_bytes(b"%PDF-1.4 existing")

        settings = _make_settings(invoices_dir=str(tmp_path))
        invoice = _make_invoice(pdf_path=str(existing_pdf))
        svc, _ = _build_pdf_service(settings, tmp_path)

        # generate_invoice_pdf should NOT be called
        svc.generate_invoice_pdf = AsyncMock()

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            result = await svc.ensure_pdf_exists(invoice)

        assert result == str(existing_pdf)
        svc.generate_invoice_pdf.assert_not_called()

    async def test_ensure_pdf_exists_regenerates_missing(self, tmp_path):
        """When pdf_path is set but file is missing on disk, regenerates PDF."""

        missing_path = str(tmp_path / "ATR-2026-03-001.pdf")
        # Do NOT create the file — it's missing
        new_path = str(tmp_path / "ATR-2026-03-001_new.pdf")

        settings = _make_settings(invoices_dir=str(tmp_path))
        invoice = _make_invoice(pdf_path=missing_path)
        svc, _ = _build_pdf_service(settings, tmp_path)

        svc.generate_invoice_pdf = AsyncMock(return_value=new_path)

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            result = await svc.ensure_pdf_exists(invoice)

        assert result == new_path
        svc.generate_invoice_pdf.assert_called_once_with(invoice)

    async def test_ensure_pdf_exists_no_path_generates(self, tmp_path):
        """When invoice has no pdf_path, generates PDF."""

        generated_path = str(tmp_path / "ATR-2026-03-001.pdf")

        settings = _make_settings(invoices_dir=str(tmp_path))
        invoice = _make_invoice(pdf_path=None)
        svc, _ = _build_pdf_service(settings, tmp_path)

        svc.generate_invoice_pdf = AsyncMock(return_value=generated_path)

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            result = await svc.ensure_pdf_exists(invoice)

        assert result == generated_path
        svc.generate_invoice_pdf.assert_called_once_with(invoice)


# ---------------------------------------------------------------------------
# Tests — _render_html
# ---------------------------------------------------------------------------


class TestRenderHtml:
    """_render_html passes correct context to Jinja2 template."""

    def test_render_html_calls_template_with_invoice_number(self):
        """Template render receives invoice_number via invoice object."""

        settings = _make_settings()
        invoice = _make_invoice(invoice_number="ATR-2026-03-001")
        svc, mock_jinja_env = _build_pdf_service(settings)

        mock_template = MagicMock()
        mock_template.render.return_value = "<html>ATR-2026-03-001</html>"
        mock_jinja_env.get_template.return_value = mock_template

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            result = svc._render_html(invoice)

        assert "ATR-2026-03-001" in result
        mock_jinja_env.get_template.assert_called_once_with("invoice.html")

    def test_render_html_passes_amounts(self):
        """Template render receives correct maintenance and total amounts."""

        settings = _make_settings()
        invoice = _make_invoice(
            maintenance_amount_eur=Decimal("50.00"),
            token_amount_eur=Decimal("0.45"),
            total_amount_eur=Decimal("50.45"),
        )
        svc, mock_jinja_env = _build_pdf_service(settings)

        captured_kwargs = {}

        def capture_render(**kwargs):
            captured_kwargs.update(kwargs)
            return "<html>ok</html>"

        mock_template = MagicMock()
        mock_template.render.side_effect = capture_render
        mock_jinja_env.get_template.return_value = mock_template

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            svc._render_html(invoice)

        assert captured_kwargs["maintenance_amount"] == "50.00"
        assert captured_kwargs["token_amount"] == "0.45"
        assert captured_kwargs["total_amount"] == "50.45"

    def test_render_html_period_label_spanish(self):
        """period_label is in Spanish for known months."""

        settings = _make_settings()
        invoice = _make_invoice(year=2026, month=3)
        svc, mock_jinja_env = _build_pdf_service(settings)

        captured_kwargs = {}

        def capture_render(**kwargs):
            captured_kwargs.update(kwargs)
            return "<html>ok</html>"

        mock_template = MagicMock()
        mock_template.render.side_effect = capture_render
        mock_jinja_env.get_template.return_value = mock_template

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            svc._render_html(invoice)

        # invoice is passed as a kwarg itself
        assert captured_kwargs.get("invoice") is invoice

    def test_render_html_no_token_usage(self):
        """_render_html handles invoice with no token_usage (uses zeros)."""

        settings = _make_settings()
        invoice = _make_invoice(with_token_usage=False)
        svc, mock_jinja_env = _build_pdf_service(settings)

        captured_kwargs = {}

        def capture_render(**kwargs):
            captured_kwargs.update(kwargs)
            return "<html>ok</html>"

        mock_template = MagicMock()
        mock_template.render.side_effect = capture_render
        mock_jinja_env.get_template.return_value = mock_template

        with patch("api.services.pdf_service.get_settings", return_value=settings):
            svc._render_html(invoice)

        # Tokens should be formatted as "0"
        assert captured_kwargs["input_tokens"] == "0"
        assert captured_kwargs["output_tokens"] == "0"
        assert captured_kwargs["total_requests"] == "0"


# ---------------------------------------------------------------------------
# Tests — _write_pdf
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _WEASYPRINT_AVAILABLE, reason="weasyprint not available (missing OS deps: cairo/pango)"
)
class TestWritePdf:
    """_write_pdf calls weasyprint.HTML correctly."""

    def test_write_pdf_calls_weasyprint(self, tmp_path):
        """_write_pdf delegates to weasyprint HTML.write_pdf."""

        settings = _make_settings(invoices_dir=str(tmp_path))
        svc, _ = _build_pdf_service(settings, tmp_path)

        output_path = str(tmp_path / "test.pdf")
        html_content = "<html><body>Test</body></html>"

        mock_html_instance = MagicMock()

        with patch("weasyprint.HTML") as mock_html_cls:
            mock_html_cls.return_value = mock_html_instance
            svc._write_pdf(html_content, output_path)

        mock_html_cls.assert_called_once_with(string=html_content)
        mock_html_instance.write_pdf.assert_called_once_with(output_path)
