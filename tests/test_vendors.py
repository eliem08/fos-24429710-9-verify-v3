"""Tests for Dynamic Vendor Management and Custom Vendor Recognition."""

import pytest
from invoiceledger.models import Vendor
from invoiceledger.storage import Storage
from invoiceledger.extractor import Extractor


def test_dynamic_vendor_storage_crud(tmp_path):
    storage = Storage(str(tmp_path / "test_vendors.db"))
    
    # Check default seeded vendors
    vendors = storage.list_vendors()
    assert len(vendors) >= 5

    # Add custom vendor
    new_v = Vendor(
        id="v-custom-1",
        name="BuildRight Lumber Co",
        aliases=["BuildRight", "Build Right"],
        contact_email="billing@buildright.com",
        default_job_name="101 Main St Remodel",
        default_cost_code="06-Framing",
    )
    saved = storage.save_vendor(new_v)
    assert saved.id == "v-custom-1"

    retrieved = storage.get_vendor("v-custom-1")
    assert retrieved is not None
    assert retrieved.name == "BuildRight Lumber Co"
    assert "BuildRight" in retrieved.aliases

    # Extractor with dynamic vendor
    extractor = Extractor()
    extractor.load_vendors_from_storage(storage)
    
    sample_text = "INVOICE\nBuild Right Materials Supply\nInvoice #BR-990\nDate: 2026-08-15\nTotal: $1,200.00"
    vendor_norm, conf = extractor.normalize_vendor(sample_text)
    assert vendor_norm == "BuildRight Lumber Co"
    assert conf >= 0.90
