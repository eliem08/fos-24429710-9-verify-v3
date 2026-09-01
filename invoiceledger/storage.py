"""SQLite persistence for InvoiceLedger."""

import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .models import (
    InvoiceStatus,
    ExtractedInvoice,
    Job,
    VendorRule,
    ColumnMappingTemplate,
)


class Storage:
    def __init__(self, db_path: str = "invoiceledger.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                source_filename TEXT,
                vendor_name TEXT,
                invoice_number TEXT,
                invoice_date TEXT,
                due_date TEXT,
                po_number TEXT,
                total_amount REAL,
                tax_amount REAL,
                subtotal_amount REAL,
                job_id TEXT,
                job_name TEXT,
                cost_code TEXT,
                status TEXT,
                confidence_score REAL,
                file_hash TEXT,
                archive_path TEXT,
                raw_text TEXT,
                created_at TEXT,
                reviewed_at TEXT,
                notes TEXT,
                matched_rule_id TEXT
            )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inv_hash ON invoices(file_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inv_vendor ON invoices(vendor_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inv_status ON invoices(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inv_job ON invoices(job_name)")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                client_name TEXT,
                budget_total REAL,
                cost_code_budgets TEXT,
                status TEXT,
                created_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                vendor_pattern TEXT,
                match_type TEXT,
                job_name TEXT,
                cost_code TEXT,
                priority INTEGER,
                is_active INTEGER,
                created_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS mappings (
                id TEXT PRIMARY KEY,
                template_name TEXT UNIQUE,
                columns TEXT,
                is_default INTEGER
            )
            """)
            conn.commit()

        self.seed_defaults()

    def seed_defaults(self):
        # Default jobs
        if not self.list_jobs():
            default_jobs = [
                Job(
                    id="job-101",
                    name="101 Main St Remodel",
                    client_name="Oakwood Holdings",
                    budget_total=85000.0,
                    cost_code_budgets={
                        "03-Concrete": 12000.0,
                        "06-Framing": 25000.0,
                        "07-Roofing": 15000.0,
                        "09-Finishes": 18000.0,
                        "15-Mechanical/Plumbing": 8000.0,
                        "16-Electrical": 7000.0,
                    },
                ),
                Job(
                    id="job-204",
                    name="204 Pine Ridge Commercial",
                    client_name="Apex Development Corp",
                    budget_total=175000.0,
                    cost_code_budgets={
                        "02-Site Work": 20000.0,
                        "03-Concrete": 35000.0,
                        "06-Framing": 45000.0,
                        "15-Mechanical/Plumbing": 40000.0,
                        "16-Electrical": 35000.0,
                    },
                ),
                Job(
                    id="job-310",
                    name="310 Elm Creek New Build",
                    client_name="Highland Homes LLC",
                    budget_total=240000.0,
                    cost_code_budgets={
                        "02-Site Work": 30000.0,
                        "03-Concrete": 40000.0,
                        "06-Framing": 60000.0,
                        "07-Roofing": 25000.0,
                        "08-Doors & Windows": 20000.0,
                        "09-Finishes": 35000.0,
                        "15-Mechanical/Plumbing": 15000.0,
                        "16-Electrical": 15000.0,
                    },
                ),
            ]
            for j in default_jobs:
                self.save_job(j)

        # Default rules
        if not self.list_rules():
            default_rules = [
                VendorRule(
                    id="rule-1",
                    vendor_pattern="Home Depot",
                    match_type="contains",
                    job_name="101 Main St Remodel",
                    cost_code="06-Framing",
                    priority=10,
                ),
                VendorRule(
                    id="rule-2",
                    vendor_pattern="ABC Supply",
                    match_type="contains",
                    job_name="101 Main St Remodel",
                    cost_code="07-Roofing",
                    priority=20,
                ),
                VendorRule(
                    id="rule-3",
                    vendor_pattern="84 Lumber",
                    match_type="contains",
                    job_name="310 Elm Creek New Build",
                    cost_code="06-Framing",
                    priority=30,
                ),
                VendorRule(
                    id="rule-4",
                    vendor_pattern="Ferguson",
                    match_type="contains",
                    job_name="204 Pine Ridge Commercial",
                    cost_code="15-Mechanical/Plumbing",
                    priority=40,
                ),
                VendorRule(
                    id="rule-5",
                    vendor_pattern="Fastenal",
                    match_type="contains",
                    job_name="204 Pine Ridge Commercial",
                    cost_code="16-Electrical",
                    priority=50,
                ),
            ]
            for r in default_rules:
                self.save_rule(r)

        # Default column mapping templates
        if not self.list_mappings():
            default_templates = [
                ColumnMappingTemplate(
                    id="tpl-default",
                    template_name="Default Contractor P&L",
                    columns={
                        "Date": "invoice_date",
                        "Job": "job_name",
                        "Cost Code": "cost_code",
                        "Vendor": "vendor_name",
                        "Invoice #": "invoice_number",
                        "PO #": "po_number",
                        "Amount ($)": "total_amount",
                        "Status": "status",
                        "Receipt Link": "archive_path",
                    },
                    is_default=True,
                ),
                ColumnMappingTemplate(
                    id="tpl-quickbooks",
                    template_name="QuickBooks Import Layout",
                    columns={
                        "Date": "invoice_date",
                        "Transaction Type": "status",
                        "Num": "invoice_number",
                        "Name": "vendor_name",
                        "Memo/PO": "po_number",
                        "Class/Job": "job_name",
                        "Account/CostCode": "cost_code",
                        "Amount": "total_amount",
                        "Attachment": "archive_path",
                    },
                    is_default=False,
                ),
                ColumnMappingTemplate(
                    id="tpl-costing",
                    template_name="Job Costing Detailed",
                    columns={
                        "Project": "job_name",
                        "Cost Code": "cost_code",
                        "Vendor Name": "vendor_name",
                        "Invoice Number": "invoice_number",
                        "PO Number": "po_number",
                        "Invoice Date": "invoice_date",
                        "Spend Amount": "total_amount",
                        "Audit Link": "archive_path",
                    },
                    is_default=False,
                ),
            ]
            for t in default_templates:
                self.save_mapping(t)

    # --- Invoices CRUD ---
    def save_invoice(self, inv: ExtractedInvoice) -> ExtractedInvoice:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO invoices VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """, (
                inv.id,
                inv.source_filename,
                inv.vendor_name,
                inv.invoice_number,
                inv.invoice_date,
                inv.due_date,
                inv.po_number,
                inv.total_amount,
                inv.tax_amount,
                inv.subtotal_amount,
                inv.job_id,
                inv.job_name,
                inv.cost_code,
                inv.status.value if isinstance(inv.status, InvoiceStatus) else str(inv.status),
                inv.confidence_score,
                inv.file_hash,
                inv.archive_path,
                inv.raw_text,
                inv.created_at,
                inv.reviewed_at,
                inv.notes,
                inv.matched_rule_id,
            ))
            conn.commit()
        return inv

    def get_invoice(self, inv_id: str) -> Optional[ExtractedInvoice]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["status"] = InvoiceStatus(d["status"])
            return ExtractedInvoice(**d)

    def list_invoices(
        self,
        status: Optional[str] = None,
        job_name: Optional[str] = None,
        vendor: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[ExtractedInvoice]:
        query = "SELECT * FROM invoices WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if job_name:
            query += " AND job_name = ?"
            params.append(job_name)
        if vendor:
            query += " AND vendor_name LIKE ?"
            params.append(f"%{vendor}%")
        if search:
            query += " AND (vendor_name LIKE ? OR invoice_number LIKE ? OR po_number LIKE ? OR job_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])

        query += " ORDER BY created_at DESC"

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["status"] = InvoiceStatus(d["status"])
                results.append(ExtractedInvoice(**d))
            return results

    def update_invoice(self, inv: ExtractedInvoice) -> ExtractedInvoice:
        return self.save_invoice(inv)

    def delete_invoice(self, inv_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
            conn.commit()
            return cur.rowcount > 0

    def find_duplicate(
        self,
        vendor_name: str,
        invoice_number: str,
        total_amount: float,
        file_hash: str,
    ) -> Optional[ExtractedInvoice]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            # 1. Exact hash match
            cur.execute("SELECT * FROM invoices WHERE file_hash = ? AND status != 'rejected'", (file_hash,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["status"] = InvoiceStatus(d["status"])
                return ExtractedInvoice(**d)

            # 2. Triplet match (Vendor, Invoice Number, Amount)
            norm_vendor = vendor_name.strip().lower()
            norm_inv = invoice_number.strip().lower()
            rounded_amt = round(total_amount, 2)

            cur.execute("""
                SELECT * FROM invoices 
                WHERE LOWER(TRIM(invoice_number)) = ? 
                AND ROUND(total_amount, 2) = ?
                AND status != 'rejected'
            """, (norm_inv, rounded_amt))
            rows = cur.fetchall()
            for r in rows:
                d = dict(r)
                if norm_vendor in d["vendor_name"].lower() or d["vendor_name"].lower() in norm_vendor:
                    d["status"] = InvoiceStatus(d["status"])
                    return ExtractedInvoice(**d)

        return None

    # --- Jobs CRUD ---
    def save_job(self, job: Job) -> Job:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id,
                job.name,
                job.client_name,
                job.budget_total,
                json.dumps(job.cost_code_budgets),
                job.status,
                job.created_at,
            ))
            conn.commit()
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["cost_code_budgets"] = json.loads(d["cost_code_budgets"] or "{}")
            return Job(**d)

    def get_job_by_name(self, name: str) -> Optional[Job]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jobs WHERE LOWER(name) = LOWER(?)", (name.strip(),))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["cost_code_budgets"] = json.loads(d["cost_code_budgets"] or "{}")
            return Job(**d)

    def list_jobs(self) -> List[Job]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM jobs ORDER BY name ASC")
            rows = cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["cost_code_budgets"] = json.loads(d["cost_code_budgets"] or "{}")
                results.append(Job(**d))
            return results

    def delete_job(self, job_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cur.rowcount > 0

    # --- Rules CRUD ---
    def save_rule(self, rule: VendorRule) -> VendorRule:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rule.id,
                rule.vendor_pattern,
                rule.match_type,
                rule.job_name,
                rule.cost_code,
                rule.priority,
                1 if rule.is_active else 0,
                rule.created_at,
            ))
            conn.commit()
        return rule

    def get_rule(self, rule_id: str) -> Optional[VendorRule]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["is_active"] = bool(d["is_active"])
            return VendorRule(**d)

    def list_rules(self) -> List[VendorRule]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM rules ORDER BY priority ASC, created_at DESC")
            rows = cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["is_active"] = bool(d["is_active"])
                results.append(VendorRule(**d))
            return results

    def delete_rule(self, rule_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            conn.commit()
            return cur.rowcount > 0

    # --- Column Mappings CRUD ---
    def save_mapping(self, mapping: ColumnMappingTemplate) -> ColumnMappingTemplate:
        with self._get_connection() as conn:
            cur = conn.cursor()
            if mapping.is_default:
                cur.execute("UPDATE mappings SET is_default = 0")
            cur.execute("""
            INSERT OR REPLACE INTO mappings VALUES (?, ?, ?, ?)
            """, (
                mapping.id,
                mapping.template_name,
                json.dumps(mapping.columns),
                1 if mapping.is_default else 0,
            ))
            conn.commit()
        return mapping

    def get_mapping(self, mapping_id: str) -> Optional[ColumnMappingTemplate]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM mappings WHERE id = ?", (mapping_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["columns"] = json.loads(d["columns"])
            d["is_default"] = bool(d["is_default"])
            return ColumnMappingTemplate(**d)

    def get_default_mapping(self) -> ColumnMappingTemplate:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM mappings WHERE is_default = 1 LIMIT 1")
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["columns"] = json.loads(d["columns"])
                d["is_default"] = bool(d["is_default"])
                return ColumnMappingTemplate(**d)
            # fallback
            return ColumnMappingTemplate(
                id="tpl-default",
                template_name="Default Contractor P&L",
                columns={
                    "Date": "invoice_date",
                    "Job": "job_name",
                    "Cost Code": "cost_code",
                    "Vendor": "vendor_name",
                    "Invoice #": "invoice_number",
                    "PO #": "po_number",
                    "Amount ($)": "total_amount",
                    "Status": "status",
                    "Receipt Link": "archive_path",
                },
                is_default=True,
            )

    def list_mappings(self) -> List[ColumnMappingTemplate]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM mappings ORDER BY is_default DESC, template_name ASC")
            rows = cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["columns"] = json.loads(d["columns"])
                d["is_default"] = bool(d["is_default"])
                results.append(ColumnMappingTemplate(**d))
            return results
