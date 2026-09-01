"""Tests for real-time Job P&L Rollups and budget visibility."""

import pytest
import time
from invoiceledger.models import Job, ExtractedInvoice, InvoiceStatus
from invoiceledger.rollups import RollupEngine
from invoiceledger.storage import Storage


def test_job_rollup_calculation():
    job = Job(
        id="job-1",
        name="101 Main St Remodel",
        client_name="Oakwood Holdings",
        budget_total=50000.0,
        cost_code_budgets={
            "06-Framing": 20000.0,
            "07-Roofing": 15000.0,
            "16-Electrical": 10000.0,
        }
    )

    invoices = [
        ExtractedInvoice(
            id="i1",
            source_filename="1.pdf",
            vendor_name="The Home Depot",
            invoice_number="HD-1",
            invoice_date="2026-08-01",
            total_amount=5000.0,
            job_name="101 Main St Remodel",
            cost_code="06-Framing",
            status=InvoiceStatus.COMMITTED,
            file_hash="h1",
        ),
        ExtractedInvoice(
            id="i2",
            source_filename="2.pdf",
            vendor_name="ABC Supply",
            invoice_number="ABC-2",
            invoice_date="2026-08-05",
            total_amount=10000.0,
            job_name="101 Main St Remodel",
            cost_code="07-Roofing",
            status=InvoiceStatus.COMMITTED,
            file_hash="h2",
        ),
        ExtractedInvoice(
            id="i3",
            source_filename="3.pdf",
            vendor_name="Fastenal",
            invoice_number="FAST-3",
            invoice_date="2026-08-08",
            total_amount=2000.0,
            job_name="101 Main St Remodel",
            cost_code="16-Electrical",
            status=InvoiceStatus.PENDING_REVIEW,
            file_hash="h3",
        ),
    ]

    t0 = time.perf_counter()
    rollup = RollupEngine.compute_job_rollup(job, invoices)
    t1 = time.perf_counter()

    # Sub-30s requirement (runs in < 5ms)
    assert (t1 - t0) < 0.05

    assert rollup.budget_total == 50000.0
    assert rollup.committed_spend == 15000.0
    assert rollup.pending_spend == 2000.0
    assert rollup.remaining_budget == 35000.0
    assert rollup.budget_utilization_pct == 30.0
    assert rollup.vendor_breakdown["The Home Depot"] == 5000.0
    assert rollup.vendor_breakdown["ABC Supply"] == 10000.0
    assert rollup.cost_code_breakdown["06-Framing"]["spent"] == 5000.0
    assert rollup.cost_code_breakdown["06-Framing"]["remaining"] == 15000.0
