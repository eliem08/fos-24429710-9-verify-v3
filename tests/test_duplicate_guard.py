"""Tests for duplicate invoice detection."""

import pytest
from pathlib import Path
from invoiceledger.models import ExtractedInvoice, InvoiceStatus
from invoiceledger.storage import Storage
from invoiceledger.duplicate_guard import DuplicateGuard


@pytest.fixture
def storage(tmp_path):
    db_file = tmp_path / "test_dup.db"
    return Storage(str(db_file))


def test_duplicate_file_hash_detection(storage):
    inv1 = ExtractedInvoice(
        id="inv-dup-1",
        source_filename="sample.pdf",
        vendor_name="ABC Supply Co",
        invoice_number="ABC-100",
        invoice_date="2026-08-01",
        total_amount=500.0,
        file_hash="unique_hash_abc_123",
        status=InvoiceStatus.COMMITTED,
    )
    storage.save_invoice(inv1)

    # Identical file hash incoming
    inv2 = ExtractedInvoice(
        id="inv-dup-2",
        source_filename="sample_copy.pdf",
        vendor_name="ABC Supply Co",
        invoice_number="ABC-100",
        invoice_date="2026-08-01",
        total_amount=500.0,
        file_hash="unique_hash_abc_123",
        status=InvoiceStatus.PENDING_REVIEW,
    )
    is_dup, orig, reason = DuplicateGuard.check_duplicate(storage, inv2)
    assert is_dup is True
    assert orig.id == inv1.id
    assert "Duplicate file" in reason


def test_duplicate_triplet_detection(storage):
    """Given same invoice number + vendor + amount with different filename/hash, flags duplicate."""
    inv1 = ExtractedInvoice(
        id="inv-dup-3",
        source_filename="inv_first.pdf",
        vendor_name="The Home Depot",
        invoice_number="HD-8844",
        invoice_date="2026-08-10",
        total_amount=1240.50,
        file_hash="hash_alpha",
        status=InvoiceStatus.COMMITTED,
    )
    storage.save_invoice(inv1)

    # Different hash, but same vendor + invoice # + amount
    inv2 = ExtractedInvoice(
        id="inv-dup-4",
        source_filename="inv_second_scan.pdf",
        vendor_name="The Home Depot Pro",
        invoice_number="HD-8844",
        invoice_date="2026-08-10",
        total_amount=1240.50,
        file_hash="hash_beta",
        status=InvoiceStatus.PENDING_REVIEW,
    )
    is_dup, orig, reason = DuplicateGuard.check_duplicate(storage, inv2)
    assert is_dup is True
    assert orig.id == inv1.id
    assert "Duplicate invoice" in reason
