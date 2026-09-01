"""Tests for file archiving and audit link organization."""

import pytest
from pathlib import Path
from invoiceledger.archiver import Archiver, slugify


def test_slugify():
    assert slugify("The Home Depot, Inc.") == "the-home-depot-inc"
    assert slugify("101 Main St (Remodel)") == "101-main-st-remodel"


def test_archiver_folder_structure(tmp_path):
    archiver = Archiver(base_dir=str(tmp_path / "archive"))
    
    source_invoice = tmp_path / "receipt_scan.pdf"
    source_invoice.write_bytes(b"%PDF-sample-content")

    rel_path, abs_path = archiver.archive_invoice_file(
        source_path=source_invoice,
        job_name="101 Main St Remodel",
        vendor_name="The Home Depot",
        invoice_date="2026-08-10",
        invoice_number="HD-9922",
    )

    assert abs_path.exists()
    assert "101-main-st-remodel" in rel_path
    assert "the-home-depot" in rel_path
    assert "2026-08-10_hd-9922_receipt_scan.pdf" in rel_path
