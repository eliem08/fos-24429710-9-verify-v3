"""Command Line Interface for InvoiceLedger."""

import sys
import io
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

from .models import InvoiceStatus, Job, VendorRule, ColumnMappingTemplate
from .storage import Storage
from .extractor import Extractor
from .rules_engine import RulesEngine
from .duplicate_guard import DuplicateGuard
from .archiver import Archiver
from .spreadsheet import SpreadsheetManager
from .rollups import RollupEngine
from .intake import IntakeManager


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


def cmd_export(args, storage: Storage):
    template = storage.get_mapping(args.template) if args.template else storage.get_default_mapping()
    if not template:
        template = storage.get_default_mapping()

    invoices = storage.list_invoices(status="committed", job_name=args.job)
    out_path = Path(args.output) if args.output else Path(f"InvoiceLedger_Export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv")
    csv_text, summary = SpreadsheetManager.export_to_csv(invoices, template, out_path)

    print(f"[OK] Exported {summary.total_invoices} committed invoice(s) to '{out_path}'")
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

    # export
    p_export = subparsers.add_parser("export", help="Export committed ledger to Excel CSV")
    p_export.add_argument("--job", help="Filter by Job Name")
    p_export.add_argument("--output", "-o", help="Output CSV path")
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
    elif args.command == "review":
        cmd_review(args, storage)
    elif args.command == "commit":
        cmd_commit(args, storage, rules_engine)
    elif args.command == "jobs":
        cmd_jobs(args, storage)
    elif args.command == "rules":
        cmd_rules(args, storage)
    elif args.command == "export":
        cmd_export(args, storage)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        print_banner()
        parser.print_help()


if __name__ == "__main__":
    main()
