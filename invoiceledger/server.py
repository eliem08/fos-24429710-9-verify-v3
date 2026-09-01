"""FastAPI Backend Server & Web Dashboard for InvoiceLedger."""

import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .models import InvoiceStatus, ExtractedInvoice, Job, VendorRule, ColumnMappingTemplate
from .storage import Storage
from .extractor import Extractor
from .rules_engine import RulesEngine
from .duplicate_guard import DuplicateGuard
from .archiver import Archiver
from .spreadsheet import SpreadsheetManager
from .rollups import RollupEngine
from .intake import IntakeManager


app = FastAPI(title="InvoiceLedger", description="Automated Contractor Invoice Reconciler", version="0.1.0")

BASE_DIR = Path(__file__).parent
storage = Storage("invoiceledger.db")
intake_mgr = IntakeManager(storage)
rules_engine = RulesEngine(storage)

# Mount static and templates
static_dir = BASE_DIR / "static"
templates_dir = BASE_DIR / "templates"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


class CommitRequest(BaseModel):
    job_name: str
    cost_code: str
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total_amount: Optional[float] = None
    po_number: Optional[str] = None
    save_rule: bool = False


# --- HTML Dashboard View ---
@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    return templates.TemplateResponse(request, "index.html")


# --- API Stats & Rollups ---
@app.get("/api/stats")
def get_stats():
    return RollupEngine.compute_all_rollups(storage)


# --- Invoices API ---
@app.get("/api/invoices")
def list_invoices(
    status: Optional[str] = None,
    job_name: Optional[str] = None,
    vendor: Optional[str] = None,
    search: Optional[str] = None,
):
    return storage.list_invoices(status=status, job_name=job_name, vendor=vendor, search=search)


@app.get("/api/invoices/{inv_id}")
def get_invoice(inv_id: str):
    inv = storage.get_invoice(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@app.put("/api/invoices/{inv_id}")
def update_invoice(inv_id: str, data: Dict[str, Any]):
    inv = storage.get_invoice(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    for k, v in data.items():
        if hasattr(inv, k):
            setattr(inv, k, v)
    return storage.update_invoice(inv)


@app.post("/api/invoices/{inv_id}/commit")
def commit_invoice(inv_id: str, req: CommitRequest):
    inv = storage.get_invoice(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Update fields
    inv.job_name = req.job_name
    inv.cost_code = req.cost_code
    if req.vendor_name:
        inv.vendor_name = req.vendor_name
    if req.invoice_number:
        inv.invoice_number = req.invoice_number
    if req.invoice_date:
        inv.invoice_date = req.invoice_date
    if req.total_amount is not None:
        inv.total_amount = round(req.total_amount, 2)
    if req.po_number is not None:
        inv.po_number = req.po_number

    job_obj = storage.get_job_by_name(req.job_name)
    if job_obj:
        inv.job_id = job_obj.id

    inv.status = InvoiceStatus.COMMITTED
    inv.reviewed_at = datetime.now(timezone.utc).isoformat()

    # Auto-learn rule if requested
    if req.save_rule and inv.vendor_name:
        rules_engine.learn_rule_from_correction(
            storage, inv.vendor_name, req.job_name, req.cost_code
        )

    # Re-archive to reflect job folder
    archiver = Archiver()
    current_file = Path(inv.archive_path) if inv.archive_path else None
    if current_file and current_file.exists():
        rel_path, _ = archiver.archive_invoice_file(
            current_file, inv.job_name, inv.vendor_name, inv.invoice_date, inv.invoice_number
        )
        inv.archive_path = rel_path

    storage.update_invoice(inv)
    return {"ok": True, "invoice": inv}


@app.post("/api/invoices/{inv_id}/reject")
def reject_invoice(inv_id: str):
    inv = storage.get_invoice(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv.status = InvoiceStatus.REJECTED
    storage.update_invoice(inv)
    return {"ok": True, "invoice": inv}


@app.delete("/api/invoices/{inv_id}")
def delete_invoice(inv_id: str):
    ok = storage.delete_invoice(inv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"ok": True}


# --- Intake & Upload API ---
@app.post("/api/upload")
async def upload_invoices(files: List[UploadFile] = File(...)):
    upload_dir = Path("uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for f in files:
        target_path = upload_dir / f.filename
        content = await f.read()
        target_path.write_bytes(content)
        inv, ok, reason = intake_mgr.process_single_file(target_path)
        results.append({"filename": f.filename, "ok": ok, "invoice": inv, "reason": reason})
    return {"processed": len(results), "results": results}


@app.post("/api/email-sync")
async def email_sync(file: Optional[UploadFile] = File(None)):
    """Syncs from an .eml email file or processes sample inbound mailbox."""
    if file:
        content = await file.read()
        invs = intake_mgr.process_email_eml(content)
        return {"processed": len(invs), "invoices": invs}
    
    # Process demo sample files
    sample_dir = Path("sample_invoices")
    invs = intake_mgr.process_directory(sample_dir)
    return {"processed": len(invs), "invoices": invs}


# --- Jobs API ---
@app.get("/api/jobs")
def list_jobs():
    return storage.list_jobs()


@app.post("/api/jobs")
def create_job(job: Job):
    return storage.save_job(job)


@app.get("/api/jobs/{job_id}/rollup")
def get_job_rollup(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    invs = [i for i in storage.list_invoices() if i.job_name == job.name]
    return RollupEngine.compute_job_rollup(job, invs)


# --- Rules API ---
@app.get("/api/rules")
def list_rules():
    return storage.list_rules()


@app.post("/api/rules")
def create_rule(rule: VendorRule):
    return storage.save_rule(rule)


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str):
    ok = storage.delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


# --- Column Mappings API ---
@app.get("/api/mappings")
def list_mappings():
    return storage.list_mappings()


@app.post("/api/mappings")
def save_mapping(mapping: ColumnMappingTemplate):
    return storage.save_mapping(mapping)


# --- Export & Append API ---
@app.get("/api/export")
def export_csv(
    job_name: Optional[str] = None,
    template_id: Optional[str] = None,
    status: str = "committed",
):
    invoices = storage.list_invoices(status=status, job_name=job_name)
    template = storage.get_mapping(template_id) if template_id else storage.get_default_mapping()
    if not template:
        template = storage.get_default_mapping()

    csv_content, summary = SpreadsheetManager.export_to_csv(invoices, template)
    filename = f"InvoiceLedger_Export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/append")
def append_spreadsheet(
    target_path: str = Form(...),
    template_id: Optional[str] = Form(None),
    job_name: Optional[str] = Form(None),
):
    invoices = storage.list_invoices(status="committed", job_name=job_name)
    template = storage.get_mapping(template_id) if template_id else storage.get_default_mapping()
    count = SpreadsheetManager.append_to_csv(invoices, Path(target_path), template)
    return {"ok": True, "appended_rows": count, "target_file": target_path}
