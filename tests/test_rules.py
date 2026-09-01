"""Tests for Vendor Rules Engine and Auto-Learning."""

import pytest
from pathlib import Path
from invoiceledger.models import ExtractedInvoice, VendorRule, Job, InvoiceStatus
from invoiceledger.storage import Storage
from invoiceledger.rules_engine import RulesEngine


@pytest.fixture
def storage(tmp_path):
    db_file = tmp_path / "test_rules.db"
    return Storage(str(db_file))


def test_rule_matching_exact_and_contains(storage):
    engine = RulesEngine(storage)
    
    inv1 = ExtractedInvoice(
        id="test-1",
        source_filename="test.pdf",
        vendor_name="The Home Depot Pro",
        invoice_number="HD-101",
        invoice_date="2026-08-10",
        total_amount=100.0,
        file_hash="hash1",
    )
    job_name, cost_code, rule_id = engine.match_invoice(inv1)
    assert job_name == "101 Main St Remodel"
    assert cost_code == "06-Framing"

    inv2 = ExtractedInvoice(
        id="test-2",
        source_filename="test2.pdf",
        vendor_name="Ferguson Plumbing Supply",
        invoice_number="FERG-99",
        invoice_date="2026-08-11",
        total_amount=250.0,
        file_hash="hash2",
    )
    job_name, cost_code, rule_id = engine.match_invoice(inv2)
    assert job_name == "204 Pine Ridge Commercial"
    assert cost_code == "15-Mechanical/Plumbing"


def test_rule_auto_learning_from_review_correction(storage):
    """Given the user corrects a coding in the review queue, saves as rule and next invoice is auto-coded."""
    engine = RulesEngine(storage)

    # Initial invoice from unknown vendor
    inv1 = ExtractedInvoice(
        id="test-unknown-1",
        source_filename="sherwin.pdf",
        vendor_name="Sherwin-Williams Paints",
        invoice_number="SW-9988",
        invoice_date="2026-08-15",
        total_amount=450.0,
        file_hash="hash_sw1",
    )
    # Initially unassigned
    job_name, cost_code, _ = engine.match_invoice(inv1)
    assert job_name is None

    # User manually corrects / assigns and saves rule
    learned_rule = engine.learn_rule_from_correction(
        storage=storage,
        vendor_name="Sherwin-Williams Paints",
        job_name="101 Main St Remodel",
        cost_code="09-Finishes",
    )
    assert learned_rule.job_name == "101 Main St Remodel"
    assert learned_rule.cost_code == "09-Finishes"

    # Next invoice from same vendor is auto-coded!
    inv2 = ExtractedInvoice(
        id="test-unknown-2",
        source_filename="sherwin_next.pdf",
        vendor_name="Sherwin-Williams Paints",
        invoice_number="SW-9999",
        invoice_date="2026-08-20",
        total_amount=890.0,
        file_hash="hash_sw2",
    )
    job_match, code_match, rule_id = engine.match_invoice(inv2)
    assert job_match == "101 Main St Remodel"
    assert code_match == "09-Finishes"
    assert rule_id == learned_rule.id
