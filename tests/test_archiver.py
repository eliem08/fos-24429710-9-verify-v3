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


def test_archiver_collision_does_not_overwrite(tmp_path):
    archiver = Archiver(base_dir=str(tmp_path / "archive"))

    # File 1 from vendor 'A-1'
    file1 = tmp_path / "invoice1.pdf"
    file1.write_bytes(b"%PDF content from invoice 1")

    # File 2 from vendor 'A 1' (same slug 'a-1', but different content)
    file2 = tmp_path / "invoice2.pdf"
    file2.write_bytes(b"%PDF distinct content from invoice 2")

    rel_path1, abs_path1 = archiver.archive_invoice_file(
        source_path=file1,
        job_name="101 Main St Remodel",
        vendor_name="A-1 Supply",
        invoice_date="2026-08-10",
        invoice_number="INV-100",
    )

    rel_path2, abs_path2 = archiver.archive_invoice_file(
        source_path=file2,
        job_name="101 Main St Remodel",
        vendor_name="A 1 Supply",
        invoice_date="2026-08-10",
        invoice_number="INV-100",
    )

    assert abs_path1.exists()
    assert abs_path2.exists()
    assert abs_path1 != abs_path2
    assert abs_path1.read_bytes() == b"%PDF content from invoice 1"
    assert abs_path2.read_bytes() == b"%PDF distinct content from invoice 2"


def test_archiver_collision_with_identical_filenames(tmp_path):
    """Verifies that archiving two different files with identical names and invoice numbers creates unique suffixed files."""
    archiver = Archiver(base_dir=str(tmp_path / "archive"))

    src1 = tmp_path / "invoice.pdf"
    src1.write_bytes(b"%PDF version 1 invoice data")

    rel1, abs1 = archiver.archive_invoice_file(
        source_path=src1,
        job_name="101 Main St",
        vendor_name="Acme Supplies",
        invoice_date="2026-08-01",
        invoice_number="INV 100",
    )

    src2 = tmp_path / "subfolder" / "invoice.pdf"
    src2.parent.mkdir(parents=True, exist_ok=True)
    src2.write_bytes(b"%PDF version 2 different invoice data")

    rel2, abs2 = archiver.archive_invoice_file(
        source_path=src2,
        job_name="101 Main St",
        vendor_name="Acme Supplies",
        invoice_date="2026-08-01",
        invoice_number="INV-100",
    )

    assert abs1.exists()
    assert abs2.exists()
    assert abs1 != abs2
    assert abs1.read_bytes() == b"%PDF version 1 invoice data"
    assert abs2.read_bytes() == b"%PDF version 2 different invoice data"
    assert "_1" in abs2.name


def test_archiver_cloud_persistence_warning(tmp_path, monkeypatch, caplog):
    """Verifies that Archiver logs a visible warning on cloud PaaS host when local storage is used."""
    import logging
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    with caplog.at_level(logging.WARNING):
        archiver = Archiver(base_dir=str(tmp_path / "cloud_archive"))
        assert any("PERSISTENCE WARNING" in r.message or "ephemeral" in r.message.lower() for r in caplog.records)


def test_archiver_cloud_fail_fast_when_enforced(tmp_path, monkeypatch):
    """Verifies that Archiver raises RuntimeError when FAIL_ON_EPHEMERAL_STORAGE is set on a cloud host."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("FAIL_ON_EPHEMERAL_STORAGE", "true")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        Archiver(base_dir=str(tmp_path / "cloud_archive"))

    assert "DURABLE STORAGE REQUIRED" in str(exc_info.value)

