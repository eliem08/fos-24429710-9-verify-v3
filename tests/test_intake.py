"""Tests for full Intake pipeline and Email ingestion."""

import pytest
from pathlib import Path
from invoiceledger.models import InvoiceStatus
from invoiceledger.storage import Storage
from invoiceledger.intake import IntakeManager

SAMPLE_DIR = Path(__file__).parent.parent / "sample_invoices"


@pytest.fixture
def storage(tmp_path):
    db_file = tmp_path / "test_intake.db"
    return Storage(str(db_file))


def test_single_file_intake_pipeline(storage):
    intake = IntakeManager(storage)
    sample_pdf = SAMPLE_DIR / "home_depot_inv_101.pdf"

    inv, ok, reason = intake.process_single_file(sample_pdf)
    assert ok is True
    assert inv.vendor_name == "The Home Depot"
    assert inv.invoice_number == "HD-984210"
    assert inv.total_amount == 1450.75
    # Auto-routed by default Home Depot rule to 101 Main St Remodel
    assert inv.job_name == "101 Main St Remodel"
    assert inv.cost_code == "06-Framing"
    assert inv.archive_path is not None


def test_directory_batch_intake(storage):
    intake = IntakeManager(storage)
    results = intake.process_directory(SAMPLE_DIR)
    assert len(results) >= 20
    
    # Invoices are persisted in DB
    all_in_db = storage.list_invoices()
    assert len(all_in_db) >= 20


def test_email_eml_ingestion(storage, tmp_path):
    intake = IntakeManager(storage)
    
    # Create mock EML message with PDF attachment
    sample_pdf = SAMPLE_DIR / "abc_supply_inv_201.pdf"
    pdf_bytes = sample_pdf.read_bytes()
    
    import email.message
    msg = email.message.EmailMessage()
    msg["Subject"] = "Your Invoice from ABC Supply"
    msg["From"] = "invoicing@abcsupply.com"
    msg["To"] = "contractor@example.com"
    msg.set_content("Please find attached your invoice for 101 Main St.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="ABC_Invoice_55102.pdf")

    eml_bytes = msg.as_bytes()
    invs = intake.process_email_eml(eml_bytes)

    assert len(invs) == 1
    assert invs[0].vendor_name == "ABC Supply Co"
    assert invs[0].invoice_number == "ABC-55102"
    assert invs[0].total_amount == 4250.00
