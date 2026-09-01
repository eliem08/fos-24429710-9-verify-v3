"""Tests for FastAPI backend routes."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from invoiceledger.server import app, storage

client = TestClient(app)
SAMPLE_DIR = Path(__file__).parent.parent / "sample_invoices"


def test_api_stats():
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "jobs" in data
    assert "company_summary" in data


def test_api_jobs_crud():
    res = client.get("/api/jobs")
    assert res.status_code == 200
    assert len(res.json()) >= 3

    new_job = {
        "id": "job-test-api",
        "name": "999 Sunset Blvd",
        "client_name": "Sunset Builders",
        "budget_total": 95000.0,
        "cost_code_budgets": {"06-Framing": 20000.0}
    }
    create_res = client.post("/api/jobs", json=new_job)
    assert create_res.status_code == 200
    assert create_res.json()["name"] == "999 Sunset Blvd"


def test_api_upload_and_commit():
    sample_pdf = SAMPLE_DIR / "ferguson_inv_401.pdf"
    with open(sample_pdf, "rb") as f:
        res = client.post("/api/upload", files={"files": ("ferguson_inv_401.pdf", f, "application/pdf")})
    assert res.status_code == 200
    data = res.json()
    assert data["processed"] == 1
    inv_id = data["results"][0]["invoice"]["id"]

    # Review & Commit
    commit_payload = {
        "job_name": "204 Pine Ridge Commercial",
        "cost_code": "15-Mechanical/Plumbing",
        "vendor_name": "Ferguson Enterprises",
        "invoice_number": "FERG-10940",
        "invoice_date": "2026-08-04",
        "total_amount": 3640.50,
        "save_rule": True,
    }
    commit_res = client.post(f"/api/invoices/{inv_id}/commit", json=commit_payload)
    assert commit_res.status_code == 200
    committed = commit_res.json()["invoice"]
    assert committed["status"] == "committed"
    assert committed["total_amount"] == 3640.50


def test_api_export_csv():
    res = client.get("/api/export?status=committed")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
