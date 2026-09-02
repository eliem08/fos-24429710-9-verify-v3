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

from .models import (
    InvoiceStatus,
    ExtractedInvoice,
    Job,
    Vendor,
    VendorRule,
    ColumnMappingTemplate,
    EmailSourceConfig,
    PortalSourceConfig,
)
from .storage import Storage
from .extractor import Extractor
from .rules_engine import RulesEngine
from .duplicate_guard import DuplicateGuard
from .archiver import Archiver
from .spreadsheet import SpreadsheetManager
from .rollups import RollupEngine
from .intake import IntakeManager
from .scheduler import IntakeWorker
import logging

logger = logging.getLogger("invoiceledger.server")

def _is_cloud_environment() -> bool:
    """Detects whether code is executing in a PaaS or container cloud environment."""
    cloud_indicators = [
        "RENDER", "DYNO", "FLY_APP_NAME", "FLY_ALLOC_ID", "RAILWAY_ENVIRONMENT",
        "RAILWAY_STATIC_URL", "HEROKU_APP_ID", "HEROKU_DYNO_ID", "VERCEL",
        "AWS_LAMBDA_FUNCTION_NAME", "K_SERVICE", "KOYEB_APP_NAME",
        "CONTAINER", "DOCKER_CONTAINER", "KUBERNETES_SERVICE_HOST",
        "COOLIFY_APP_ID", "CAPROVER_APP_NAME"
    ]
    if any(os.environ.get(k) for k in cloud_indicators):
        return True
    env_name = os.environ.get("ENVIRONMENT", os.environ.get("ENV", os.environ.get("NODE_ENV", ""))).lower().strip()
    if env_name in ("production", "prod", "staging"):
        return True
    return False

def check_startup_storage_warnings():
    if _is_cloud_environment():
        missing_durable = []
        if not (os.environ.get("S3_BUCKET") or os.environ.get("AWS_S3_BUCKET")):
            missing_durable.append("S3_BUCKET / AWS_S3_BUCKET (for durable invoice documents & attachments)")
        if not os.environ.get("DATABASE_URL"):
            missing_durable.append("DATABASE_URL (PostgreSQL connection string for durable database)")

        if missing_durable:
            msg = (
                "CRITICAL PERSISTENCE WARNING: Ephemeral local storage ('archive/', 'downloaded_invoices/', SQLite) "
                "is active in cloud PaaS environment. Archived invoice files, downloaded attachments, and database records will "
                "NOT survive a container restart or redeploy. Missing: " + ", ".join(missing_durable) + ". "
                "Set STORAGE_BACKEND=s3, S3_BUCKET, and DATABASE_URL for durable production storage."
            )
            logger.warning(msg)
            fail_on_ephemeral = os.environ.get("FAIL_ON_EPHEMERAL_STORAGE", "").lower() in ("true", "1", "yes") or \
                                os.environ.get("REQUIRE_DURABLE_STORAGE", "").lower() in ("true", "1", "yes")
            if fail_on_ephemeral:
                raise RuntimeError(
                    f"DURABLE PERSISTENCE REQUIRED ON CLOUD HOST: Missing {missing_durable}. "
                    "Configure DATABASE_URL and S3_BUCKET or set ALLOW_EPHEMERAL_STORAGE=true to override."
                )

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    check_startup_storage_warnings()
    yield

app = FastAPI(
    title="InvoiceLedger",
    description="Automated Contractor Invoice Reconciler",
    version="0.1.0",
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).parent
storage = Storage()
intake_mgr = IntakeManager(storage)
rules_engine = RulesEngine(storage)
worker = IntakeWorker(intake_mgr, interval_seconds=int(os.environ.get("SYNC_INTERVAL_SECONDS", "60")))
check_startup_storage_warnings()

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


class SyncSpreadsheetRequest(BaseModel):
    job_name: str
    spreadsheet_path: Optional[str] = None
    template_id: Optional[str] = None


class EmailFetchRequest(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = 993
    username: Optional[str] = None
    password: Optional[str] = None
    mailbox: Optional[str] = "INBOX"
    use_ssl: Optional[bool] = True
    auto_commit: Optional[bool] = True


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

    saved_inv = storage.update_invoice(inv)

    # Update Job P&L spreadsheet if configured
    if job_obj and job_obj.spreadsheet_path:
        try:
            all_job_invs = storage.list_invoices(job_name=job_obj.name)
            SpreadsheetManager.update_job_pl_spreadsheet(
                job=job_obj,
                invoices=all_job_invs,
                spreadsheet_path=Path(job_obj.spreadsheet_path),
            )
        except Exception:
            pass

    return {"ok": True, "invoice": saved_inv}


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


# --- Intake & Automated Fetching API ---
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

    sample_dir = Path("sample_invoices")
    invs = intake_mgr.process_directory(sample_dir)
    return {"processed": len(invs), "invoices": invs}


@app.get("/api/intake/check-email")
@app.post("/api/intake/check-email")
def check_email_api():
    """Triggers one on-demand email poll cycle for configured IMAP mailbox.
    Returns clear 'not configured' response if IMAP credentials are not set in environment.
    """
    imap_user = os.environ.get("IMAP_USERNAME") or os.environ.get("IMAP_USER")
    imap_pass = os.environ.get("IMAP_PASSWORD")
    imap_host = os.environ.get("IMAP_HOST") or os.environ.get("IMAP_SERVER")

    if not imap_user or not imap_pass or not imap_host:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "configured": False,
                "status": "not configured",
                "message": "IMAP credentials (IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD) are not configured in environment.",
                "processed_count": 0,
                "invoices": [],
            }
        )

    try:
        invoices = intake_mgr.fetch_and_process_emails(auto_commit_if_confident=True)
        return {
            "ok": True,
            "configured": True,
            "status": "success",
            "processed_count": len(invoices),
            "invoices": invoices,
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "configured": True,
                "status": "error",
                "message": f"Email polling failed: {str(e)}",
            }
        )


@app.post("/api/intake/fetch-emails")
def fetch_emails_api(req: Optional[EmailFetchRequest] = None):
    """Triggers automated IMAP/POP3 email inbox fetch and attachment ingestion."""
    cfg = None
    auto_commit = True
    if req and req.host and req.username and req.password:
        cfg = EmailSourceConfig(
            host=req.host,
            port=req.port or 993,
            username=req.username,
            password=req.password,
            mailbox=req.mailbox or "INBOX",
            use_ssl=req.use_ssl if req.use_ssl is not None else True,
        )
        auto_commit = req.auto_commit if req.auto_commit is not None else True

    invoices = intake_mgr.fetch_and_process_emails(config=cfg, auto_commit_if_confident=auto_commit)
    return {"ok": True, "downloaded_count": len(invoices), "invoices": invoices}


@app.post("/api/intake/poll")
def poll_intake_api():
    """Runs a full automated ingestion and reconciliation cycle across emails, hot folders, and portals."""
    summary = intake_mgr.poll_and_ingest()
    return {"ok": True, "summary": summary}


@app.get("/api/intake/daemon/status")
def get_daemon_status():
    return worker.get_status()


@app.post("/api/intake/daemon/start")
def start_daemon():
    worker.start()
    return {"ok": True, "status": worker.get_status()}


@app.post("/api/intake/daemon/stop")
def stop_daemon():
    worker.stop()
    return {"ok": True, "status": worker.get_status()}


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


@app.get("/api/jobs/{job_id}/export.xlsx")
def export_job_rollup_excel(job_id: str):
    """Exports the per-job P&L rollup and itemized ledger as a downloadable Excel spreadsheet (.xlsx)."""
    job = storage.get_job(job_id)
    if not job:
        job = storage.get_job_by_name(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    invoices = [i for i in storage.list_invoices() if i.job_name == job.name]
    template = storage.get_default_mapping()
    excel_bytes, summary = SpreadsheetManager.export_to_excel(invoices, [job], template=template)
    filename = f"{job.name.replace(' ', '_')}_PL.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --- Vendors API ---
@app.get("/api/vendors")
def list_vendors():
    return storage.list_vendors()


@app.post("/api/vendors")
def create_vendor(vendor: Vendor):
    saved = storage.save_vendor(vendor)
    intake_mgr.extractor.register_vendor(vendor.name, vendor.aliases)
    return saved


@app.delete("/api/vendors/{vendor_id}")
def delete_vendor(vendor_id: str):
    ok = storage.delete_vendor(vendor_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"ok": True}


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


# --- Export & Spreadsheet API ---
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


@app.get("/api/export/excel")
def export_excel(
    job_name: Optional[str] = None,
    template_id: Optional[str] = None,
    status: str = "committed",
):
    invoices = storage.list_invoices(status=status, job_name=job_name)
    template = storage.get_mapping(template_id) if template_id else storage.get_default_mapping()
    jobs = [storage.get_job_by_name(job_name)] if job_name else storage.list_jobs()
    jobs = [j for j in jobs if j is not None]

    excel_bytes, summary = SpreadsheetManager.export_to_excel(invoices, jobs, template=template)
    filename = f"InvoiceLedger_JobCosting_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/spreadsheet/sync")
def sync_job_spreadsheet(req: SyncSpreadsheetRequest):
    """Synchronizes committed invoices to a Job P&L spreadsheet (.xlsx or .csv)."""
    job = storage.get_job_by_name(req.job_name)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    target_path = Path(req.spreadsheet_path or job.spreadsheet_path or f"{job.name.replace(' ', '_')}_PL.xlsx")
    template = storage.get_mapping(req.template_id) if req.template_id else storage.get_default_mapping()
    invoices = storage.list_invoices(job_name=job.name)

    ok = SpreadsheetManager.update_job_pl_spreadsheet(
        job=job,
        invoices=invoices,
        spreadsheet_path=target_path,
        template=template,
    )
    job.spreadsheet_path = str(target_path)
    storage.save_job(job)

    return {
        "ok": ok,
        "job_name": job.name,
        "spreadsheet_path": str(target_path),
        "reconciled_invoices_count": len([i for i in invoices if i.status == InvoiceStatus.COMMITTED]),
    }


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
