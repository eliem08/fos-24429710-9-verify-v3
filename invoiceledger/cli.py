"""Command Line Interface for InvoiceLedger."""

import sys
import io
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Ensure Windows-safe console output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .models import InvoiceStatus, Job, Vendor, VendorRule, ColumnMappingTemplate, EmailSourceConfig
from .storage import Storage
from .extractor import Extractor
from .rules_engine import RulesEngine
from .duplicate_guard import DuplicateGuard
from .archiver import Archiver
from .spreadsheet import SpreadsheetManager
from .rollups import RollupEngine
from .intake import IntakeManager
from .email_fetcher import EmailFetcher
from .scheduler import IntakeWorker


def print_banner():
    print("=" * 65)
    print(" [InvoiceLedger] Automated Vendor Invoice & P&L Reconciler")
    print("=" * 65)


def cmd_scan(args, storage: Storage, intake: IntakeManager):
    path = Path(args.path)
    if not path.exists():
        print(f"[ERROR] Path '{args.path}' does not exist.")
        sys.exit(1)

    print(f"[SCAN] Scanning '{args.path}' for vendor invoices...")
    if path.is_file():
        inv, ok, reason = intake.process_single_file(path)
        print(f"-> File: {path.name}")
        print(f"   Vendor:       {inv.vendor_name}")
        print(f"   Invoice #:    {inv.invoice_number}")
        print(f"   Date:         {inv.invoice_date}")
        print(f"   Total:        ${inv.total_amount:.2f}")
        print(f"   PO #:         {inv.po_number or 'None'}")
        print(f"   Target Job:   {inv.job_name or 'Unassigned (in review queue)'}")
        print(f"   Cost Code:    {inv.cost_code or 'Uncategorized'}")
        print(f"   Confidence:   {int(inv.confidence_score * 100)}%")
        print(f"   Status:       {inv.status.value}")
        print(f"   Result:       {reason}")
    else:
        results = intake.process_directory(path)
        print(f"[OK] Processed {len(results)} invoice(s) from directory:")
        for inv in results:
            print(f" - [{inv.status.value.upper()}] {inv.vendor_name} #{inv.invoice_number} | ${inv.total_amount:.2f} | Job: {inv.job_name or 'Unassigned'}")


def cmd_fetch_emails(args, intake: IntakeManager):
    import os

    print("[EMAIL] Connecting to vendor invoice mailbox...")
    host = getattr(args, "host", None) or os.environ.get("IMAP_HOST") or os.environ.get("IMAP_SERVER")
    username = getattr(args, "username", None) or os.environ.get("IMAP_USERNAME") or os.environ.get("IMAP_USER")
    password = os.environ.get("IMAP_PASSWORD")

    if not password and host and username and sys.stdin.isatty():
        try:
            import getpass
            password = getpass.getpass(f"Enter password for {username}@{host}: ")
        except Exception:
            pass

    cfg = None
    if host and username and password:
        cfg = EmailSourceConfig(
            host=host,
            port=args.port or int(os.environ.get("IMAP_PORT", "993")),
            username=username,
            password=password,
            mailbox=args.mailbox or os.environ.get("IMAP_MAILBOX", "INBOX"),
            use_ssl=not args.no_ssl,
        )
    invoices = intake.fetch_and_process_emails(config=cfg, auto_commit_if_confident=args.auto_commit)
    print(f"[OK] Downloaded and processed {len(invoices)} invoice(s) from email.")
    for inv in invoices:
        print(f" - [{inv.status.value.upper()}] {inv.vendor_name} #{inv.invoice_number} | ${inv.total_amount:.2f} | Job: {inv.job_name or 'Unassigned'}")


def cmd_poll(args, intake: IntakeManager):
    print("[POLL] Running full automated intake & spreadsheet reconciliation cycle...")
    watch_dirs = [Path(d) for d in args.watch_dirs] if getattr(args, "watch_dirs", None) else [Path("uploads"), Path("hot_folder")]
    summary = intake.poll_and_ingest(watch_dirs=watch_dirs, auto_commit_if_confident=args.auto_commit)
    print(f"[OK] Completed intake cycle at {summary['timestamp']}:")
    print(f"   Total Ingested: {summary['total_processed']}")
    print(f"   Auto-Committed: {summary['committed_count']}")
    print(f"   Pending Review: {summary['pending_count']}")
    print(f"   Duplicates:     {summary['duplicate_count']}")


def cmd_daemon(args, intake: IntakeManager):
    interval = args.interval or 60
    print(f"[DAEMON] Starting continuous background invoice intake worker (interval: {interval}s)...")
    print("Press Ctrl+C to terminate.")
    watch_dirs = [Path(d) for d in args.watch_dirs] if getattr(args, "watch_dirs", None) else [Path("uploads"), Path("hot_folder")]
    worker = IntakeWorker(
        intake_manager=intake,
        interval_seconds=interval,
        watch_dirs=watch_dirs,
        auto_commit_if_confident=args.auto_commit,
    )
    worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[DAEMON] Stopping worker...")
        worker.stop()
        print("[DAEMON] Worker stopped cleanly.")


def cmd_review(args, storage: Storage):
    invoices = storage.list_invoices(status="pending_review")
    print(f"[REVIEW] Human Review Queue ({len(invoices)} pending):")
    if not invoices:
        print("   All caught up! No invoices pending review.")
        return

    print("-" * 65)
    for i, inv in enumerate(invoices, 1):
        print(f"[{i}] ID: {inv.id}")
        print(f"    Vendor:      {inv.vendor_name}")
        print(f"    Invoice #:   {inv.invoice_number}")
        print(f"    Date:        {inv.invoice_date}")
        print(f"    Amount:      ${inv.total_amount:.2f}")
        print(f"    Job:         {inv.job_name or 'Unassigned'}")
        print(f"    Cost Code:   {inv.cost_code or 'Unassigned'}")
        print(f"    Confidence:  {int(inv.confidence_score * 100)}%")
        print("-" * 65)


def cmd_commit(args, storage: Storage, rules_engine: RulesEngine):
    inv = storage.get_invoice(args.id)
    if not inv:
        print(f"[ERROR] Invoice ID '{args.id}' not found.")
        sys.exit(1)

    if args.job:
        inv.job_name = args.job
        job_obj = storage.get_job_by_name(args.job)
        if job_obj:
            inv.job_id = job_obj.id

    if args.cost_code:
        inv.cost_code = args.cost_code

    if args.vendor:
        inv.vendor_name = args.vendor

    if args.amount is not None:
        inv.total_amount = round(args.amount, 2)

    inv.status = InvoiceStatus.COMMITTED
    inv.reviewed_at = datetime.now(timezone.utc).isoformat()

    if args.save_rule and inv.vendor_name and inv.job_name and inv.cost_code:
        rules_engine.learn_rule_from_correction(
            storage, inv.vendor_name, inv.job_name, inv.cost_code
        )
        print(f"[RULE] Saved rule: Vendor '{inv.vendor_name}' -> Job '{inv.job_name}', Cost Code '{inv.cost_code}'")

    storage.update_invoice(inv)
    print(f"[OK] Committed invoice #{inv.invoice_number} ({inv.vendor_name}) to Job '{inv.job_name}'!")

    # Auto-update job spreadsheet if job has spreadsheet_path configured
    if inv.job_name:
        job_obj = storage.get_job_by_name(inv.job_name)
        if job_obj and job_obj.spreadsheet_path:
            all_job_invs = storage.list_invoices(job_name=inv.job_name)
            SpreadsheetManager.update_job_pl_spreadsheet(
                job=job_obj,
                invoices=all_job_invs,
                spreadsheet_path=Path(job_obj.spreadsheet_path),
            )
            print(f"[SPREADSHEET] Synchronized Job P&L to '{job_obj.spreadsheet_path}'")


def cmd_jobs(args, storage: Storage):
    data = RollupEngine.compute_all_rollups(storage)
    print(f"[JOBS] Job Costing & P&L Rollup Summary ({data['company_summary']['active_jobs_count']} active jobs):")
    print("=" * 65)
    for job in data["jobs"]:
        print(f"-> Project: {job.job_name} ({job.client_name or 'Client'})")
        print(f"    Total Budget:    ${job.budget_total:,.2f}")
        print(f"    Committed Spend: ${job.committed_spend:,.2f} ({job.budget_utilization_pct}% spent)")
        print(f"    Pending Spend:   ${job.pending_spend:,.2f}")
        print(f"    Remaining:       ${job.remaining_budget:,.2f}")
        print("    Cost Codes:")
        for code, c in job.cost_code_breakdown.items():
            print(f"      - {code:22}: ${c['spent']:>10,.2f} / ${c['budget']:>10,.2f}")
        print("-" * 65)


def cmd_rules(args, storage: Storage):
    rules = storage.list_rules()
    print(f"[RULES] Vendor Automation Rules ({len(rules)} active):")
    print("-" * 65)
    for r in rules:
        print(f" - [{r.match_type.upper()}] '{r.vendor_pattern}' -> Job: '{r.job_name}' | Code: '{r.cost_code}' (Priority {r.priority})")


def cmd_vendors(args, storage: Storage):
    if getattr(args, "add_name", None):
        import uuid
        aliases = [a.strip() for a in (args.aliases or "").split(",") if a.strip()]
        vendor = Vendor(
            id=f"v-{uuid.uuid4().hex[:6]}",
            name=args.add_name.strip(),
            aliases=aliases,
            default_job_name=args.job,
            default_cost_code=args.cost_code,
        )
        storage.save_vendor(vendor)
        print(f"[OK] Added custom vendor '{vendor.name}' with aliases {vendor.aliases}")
        return

    vendors = storage.list_vendors()
    print(f"[VENDORS] Registered Vendor Directory ({len(vendors)} vendors):")
    print("-" * 65)
    for v in vendors:
        alias_str = f" (Aliases: {', '.join(v.aliases)})" if v.aliases else ""
        print(f" - {v.name}{alias_str}")


def cmd_spreadsheet(args, storage: Storage):
    job_name = args.job
    job_obj = storage.get_job_by_name(job_name)
    if not job_obj:
        print(f"[ERROR] Job '{job_name}' not found.")
        sys.exit(1)

    out_path = Path(args.output) if args.output else Path(f"{job_obj.name.replace(' ', '_')}_PL.xlsx")
    job_invs = storage.list_invoices(job_name=job_obj.name)
    SpreadsheetManager.update_job_pl_spreadsheet(job_obj, job_invs, out_path)
    job_obj.spreadsheet_path = str(out_path)
    storage.save_job(job_obj)
    print(f"[OK] Successfully updated Job P&L spreadsheet at '{out_path}'")


def cmd_export(args, storage: Storage):
    template = storage.get_mapping(args.template) if args.template else storage.get_default_mapping()
    if not template:
        template = storage.get_default_mapping()

    invoices = storage.list_invoices(status="committed", job_name=args.job)
    fmt = getattr(args, "format", "csv") or "csv"

    if fmt == "xlsx":
        jobs = [storage.get_job_by_name(args.job)] if args.job else storage.list_jobs()
        jobs = [j for j in jobs if j is not None]
        out_path = Path(args.output) if args.output else Path(f"InvoiceLedger_Export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx")
        bytes_data, summary = SpreadsheetManager.export_to_excel(invoices, jobs, out_path, template)
        print(f"[OK] Exported {summary.total_invoices} committed invoice(s) to Excel '{out_path}'")
    else:
        out_path = Path(args.output) if args.output else Path(f"InvoiceLedger_Export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv")
        csv_text, summary = SpreadsheetManager.export_to_csv(invoices, template, out_path)
        print(f"[OK] Exported {summary.total_invoices} committed invoice(s) to CSV '{out_path}'")

    print(f"   Template:         {template.template_name}")
    print(f"   Reconciled Total: ${summary.total_amount:,.2f}")
    print(f"   Cent Exact Match: {'YES (100% cent-exact)' if summary.is_reconciled else 'NO'}")


def cmd_serve(args):
    import uvicorn
    print(f"[SERVER] Starting InvoiceLedger Web UI on http://{args.host}:{args.port} ...")
    uvicorn.run("invoiceledger.server:app", host=args.host, port=args.port, reload=False)


def main():
    parser = argparse.ArgumentParser(description="InvoiceLedger CLI")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan and ingest invoice PDF/images/directory")
    p_scan.add_argument("path", help="Path to invoice file or directory")

    # fetch-emails
    p_fetch = subparsers.add_parser("fetch-emails", help="Download and ingest invoice attachments from email mailbox")
    p_fetch.add_argument("--host", help="IMAP Host (or IMAP_HOST env var)")
    p_fetch.add_argument("--port", type=int, default=993, help="IMAP Port (default: 993)")
    p_fetch.add_argument("--username", help="Email username (or IMAP_USERNAME env var)")
    p_fetch.add_argument("--mailbox", default="INBOX", help="Mailbox folder (default: INBOX)")
    p_fetch.add_argument("--no-ssl", action="store_true", help="Disable SSL")
    p_fetch.add_argument("--auto-commit", action="store_true", help="Auto-commit confident matched invoices")

    # poll
    p_poll = subparsers.add_parser("poll", help="Run full automated intake & spreadsheet reconciliation cycle once")
    p_poll.add_argument("--watch-dirs", nargs="*", help="Watch directories to scan")
    p_poll.add_argument("--auto-commit", action="store_true", default=True, help="Auto-commit confident matches")

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="Run continuous automated background intake worker daemon")
    p_daemon.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    p_daemon.add_argument("--watch-dirs", nargs="*", help="Watch directories to monitor")
    p_daemon.add_argument("--auto-commit", action="store_true", default=True, help="Auto-commit confident matches")

    # review
    p_review = subparsers.add_parser("review", help="List invoices pending human review")

    # commit
    p_commit = subparsers.add_parser("commit", help="Commit and reconcile an invoice")
    p_commit.add_argument("id", help="Invoice ID")
    p_commit.add_argument("--job", help="Target Job Name")
    p_commit.add_argument("--cost-code", help="Target Cost Code")
    p_commit.add_argument("--vendor", help="Vendor Name")
    p_commit.add_argument("--amount", type=float, help="Total Amount ($)")
    p_commit.add_argument("--save-rule", action="store_true", help="Auto-learn rule for this vendor")

    # jobs
    p_jobs = subparsers.add_parser("jobs", help="View real-time job rollups and budget spend")

    # rules
    p_rules = subparsers.add_parser("rules", help="List vendor automation routing rules")

    # vendors
    p_vendors = subparsers.add_parser("vendors", help="List or add registered vendors")
    p_vendors.add_argument("--add-name", help="Add new vendor name")
    p_vendors.add_argument("--aliases", help="Comma-separated aliases")
    p_vendors.add_argument("--job", help="Default target job name")
    p_vendors.add_argument("--cost-code", help="Default cost code")

    # spreadsheet
    p_sheet = subparsers.add_parser("spreadsheet", help="Update or sync Job P&L Excel/CSV spreadsheet")
    p_sheet.add_argument("--job", required=True, help="Target Job Name")
    p_sheet.add_argument("--output", "-o", help="Target spreadsheet path (.xlsx or .csv)")

    # export
    p_export = subparsers.add_parser("export", help="Export committed ledger to Excel (.xlsx) or CSV")
    p_export.add_argument("--job", help="Filter by Job Name")
    p_export.add_argument("--output", "-o", help="Output file path")
    p_export.add_argument("--format", choices=["csv", "xlsx"], default="csv", help="Export format")
    p_export.add_argument("--template", "-t", help="Column mapping template ID")

    # serve
    p_serve = subparsers.add_parser("serve", help="Start FastAPI Web Dashboard")
    p_serve.add_argument("--host", default="0.0.0.0", help="Host address")
    p_serve.add_argument("--port", type=int, default=8000, help="Port number")

    args = parser.parse_args()

    storage = Storage("invoiceledger.db")
    intake = IntakeManager(storage)
    rules_engine = RulesEngine(storage)

    if args.command == "scan":
        cmd_scan(args, storage, intake)
    elif args.command == "fetch-emails":
        cmd_fetch_emails(args, intake)
    elif args.command == "poll":
        cmd_poll(args, intake)
    elif args.command == "daemon":
        cmd_daemon(args, intake)
    elif args.command == "review":
        cmd_review(args, storage)
    elif args.command == "commit":
        cmd_commit(args, storage, rules_engine)
    elif args.command == "jobs":
        cmd_jobs(args, storage)
    elif args.command == "rules":
        cmd_rules(args, storage)
    elif args.command == "vendors":
        cmd_vendors(args, storage)
    elif args.command == "spreadsheet":
        cmd_spreadsheet(args, storage)
    elif args.command == "export":
        cmd_export(args, storage)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        print_banner()
        parser.print_help()


if __name__ == "__main__":
    main()
