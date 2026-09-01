"""Tests for Spreadsheet column mapping, cent-exact reconciliation, and append."""

import pytest
import csv
from pathlib import Path
from invoiceledger.models import ExtractedInvoice, ColumnMappingTemplate, InvoiceStatus
from invoiceledger.spreadsheet import SpreadsheetManager


def test_export_cent_exact_reconciliation(tmp_path):
    """Acceptance test: Exported data reconciles exactly (to the cent) against source PDF totals for 100% of invoices."""
    invoices = [
        ExtractedInvoice(
            id="inv-1",
            source_filename="1.pdf",
            vendor_name="The Home Depot",
            invoice_number="HD-1",
            invoice_date="2026-08-01",
            total_amount=1450.75,
            job_name="101 Main St Remodel",
            cost_code="06-Framing",
            status=InvoiceStatus.COMMITTED,
            file_hash="h1",
            archive_path="archive/101-main/hd_1.pdf",
        ),
        ExtractedInvoice(
            id="inv-2",
            source_filename="2.pdf",
            vendor_name="ABC Supply Co",
            invoice_number="ABC-2",
            invoice_date="2026-08-05",
            total_amount=4250.00,
            job_name="101 Main St Remodel",
            cost_code="07-Roofing",
            status=InvoiceStatus.COMMITTED,
            file_hash="h2",
            archive_path="archive/101-main/abc_2.pdf",
        ),
        ExtractedInvoice(
            id="inv-3",
            source_filename="3.pdf",
            vendor_name="Fastenal",
            invoice_number="FAST-3",
            invoice_date="2026-08-10",
            total_amount=324.50,
            job_name="204 Pine Ridge Commercial",
            cost_code="16-Electrical",
            status=InvoiceStatus.COMMITTED,
            file_hash="h3",
            archive_path="archive/204-pine/fast_3.pdf",
        ),
    ]

    template = ColumnMappingTemplate(
        id="tpl-test",
        template_name="Test Contractor P&L",
        columns={
            "Transaction Date": "invoice_date",
            "Project": "job_name",
            "Cost Code": "cost_code",
            "Supplier": "vendor_name",
            "Voucher #": "invoice_number",
            "Total Cost ($)": "total_amount",
            "Audit Link": "archive_path",
        },
    )

    out_file = tmp_path / "Job_Costing_Export.csv"
    csv_text, summary = SpreadsheetManager.export_to_csv(invoices, template, out_file)

    # 1. Check reconciliation summary
    expected_sum = round(1450.75 + 4250.00 + 324.50, 2)
    assert summary.total_amount == expected_sum
    assert summary.is_reconciled is True
    assert summary.diff_cents == 0

    # 2. Check CSV file content & Excel UTF-8 BOM
    raw_bytes = out_file.read_bytes()
    assert raw_bytes.startswith(b"\xef\xbb\xbf"), "Exported CSV must contain UTF-8 BOM for Microsoft Excel compatibility"

    # 3. Read back CSV and verify columns and exact cent sum
    with open(out_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 3
        assert list(rows[0].keys()) == list(template.columns.keys())
        
        calculated_sum = sum(float(r["Total Cost ($)"]) for r in rows)
        assert round(calculated_sum, 2) == expected_sum


def test_append_to_spreadsheet(tmp_path):
    target_csv = tmp_path / "My_Existing_PL.csv"
    template = ColumnMappingTemplate(
        id="tpl-append",
        template_name="Default",
        columns={
            "Date": "invoice_date",
            "Job": "job_name",
            "Vendor": "vendor_name",
            "Amount": "total_amount",
        }
    )

    invoices_batch1 = [
        ExtractedInvoice(
            id="inv-a",
            source_filename="a.pdf",
            vendor_name="Home Depot",
            invoice_number="HD-A",
            invoice_date="2026-08-01",
            total_amount=100.0,
            job_name="101 Main",
            status=InvoiceStatus.COMMITTED,
            file_hash="ha",
        )
    ]
    SpreadsheetManager.append_to_csv(invoices_batch1, target_csv, template)

    invoices_batch2 = [
        ExtractedInvoice(
            id="inv-b",
            source_filename="b.pdf",
            vendor_name="84 Lumber",
            invoice_number="84L-B",
            invoice_date="2026-08-02",
            total_amount=200.0,
            job_name="101 Main",
            status=InvoiceStatus.COMMITTED,
            file_hash="hb",
        )
    ]
    count = SpreadsheetManager.append_to_csv(invoices_batch2, target_csv, template)
    assert count == 1

    with open(target_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["Vendor"] == "Home Depot"
        assert rows[1]["Vendor"] == "84 Lumber"
