"""Tests for vision-based invoice extraction using moonshotai/Kimi-K3."""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from invoiceledger.extractor import Extractor
from invoiceledger.models import ExtractedInvoice

SAMPLE_DIR = Path(__file__).parent.parent / "sample_invoices"


def test_vision_extractor_skipped_for_digital_pdf(monkeypatch):
    """Digital PDFs with a text layer should be handled directly by the text extractor without calling vision."""
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    extractor = Extractor()
    hd_pdf = SAMPLE_DIR / "home_depot_inv_101.pdf"
    assert hd_pdf.exists()

    with patch("requests.post") as mock_post:
        inv = extractor.process_file(hd_pdf)
        assert inv.vendor_name == "The Home Depot"
        assert inv.invoice_number == "HD-984210"
        assert inv.total_amount == 1450.75
        # Vision API was not called
        assert not mock_post.called


def test_vision_extractor_called_for_image_files(tmp_path, monkeypatch):
    """Image uploads (.png, .jpg) have no text layer and must always use the Kimi-K3 vision path."""
    monkeypatch.setenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-key-123")

    img_file = tmp_path / "scanned_receipt.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfakeimagebytes")

    fake_vision_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "vendor": "84 Lumber",
                        "invoice_number": "84L-99881",
                        "invoice_date": "2026-08-15",
                        "po_number": "PO-310-Trusses",
                        "total_amount": 5420.00,
                        "tax_amount": 320.00,
                        "subtotal_amount": 5100.00,
                    })
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_vision_response
    mock_resp.raise_for_status = MagicMock()

    extractor = Extractor()
    with patch("requests.post", return_value=mock_resp) as mock_post:
        inv = extractor.process_file(img_file)
        assert mock_post.called
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["model"] == "moonshotai/Kimi-K3"
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

        assert inv.vendor_name == "84 Lumber"
        assert inv.invoice_number == "84L-99881"
        assert inv.invoice_date == "2026-08-15"
        assert inv.total_amount == 5420.00
        assert inv.confidence_score >= 0.90


def test_vision_extractor_called_for_scanned_pdf_no_text_layer(tmp_path, monkeypatch):
    """PDFs with no text layer (scanned) should fall back to the Kimi-K3 vision path."""
    monkeypatch.setenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-key-123")

    # Create a dummy scanned PDF with no extractable text
    scanned_pdf = tmp_path / "scanned_invoice.pdf"
    scanned_pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")

    fake_vision_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "```json\n"
                        "{\n"
                        '  "vendor": "Ferguson Enterprises",\n'
                        '  "invoice_number": "FERG-88210",\n'
                        '  "invoice_date": "2026-08-12",\n'
                        '  "po_number": "PO-204-RoughPlumbing",\n'
                        '  "total_amount": 7890.50,\n'
                        '  "tax_amount": 450.00,\n'
                        '  "subtotal_amount": 7440.50\n'
                        "}\n"
                        "```"
                    )
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_vision_response
    mock_resp.raise_for_status = MagicMock()

    extractor = Extractor()
    with patch("requests.post", return_value=mock_resp) as mock_post:
        inv = extractor.process_file(scanned_pdf)
        assert mock_post.called
        assert inv.vendor_name == "Ferguson Enterprises"
        assert inv.invoice_number == "FERG-88210"
        assert inv.total_amount == 7890.50
        assert inv.po_number == "PO-204-RoughPlumbing"


def test_clear_error_when_vision_not_configured_for_scanned_file(tmp_path, monkeypatch):
    """When a file has no text layer and vision environment variables are unset, fail loudly with a clear error."""
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    scanned_file = tmp_path / "scanned_bill.png"
    scanned_file.write_bytes(b"\x89PNGfakebytes")

    extractor = Extractor()
    with pytest.raises(ValueError) as exc_info:
        extractor.process_file(scanned_file)

    assert "OPENAI_API_BASE" in str(exc_info.value)
    assert "OPENAI_API_KEY" in str(exc_info.value)
