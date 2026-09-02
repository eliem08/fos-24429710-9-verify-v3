"""Storage persistence for InvoiceLedger supporting SQLite and PostgreSQL."""

import os
import json
import logging
import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger("invoiceledger.storage")

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

from .models import (
    InvoiceStatus,
    ExtractedInvoice,
    Job,
    Vendor,
    VendorRule,
    ColumnMappingTemplate,
)


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


class Storage:
    def __init__(self, db_path: Optional[str] = None):
        # Check DATABASE_URL first; default to local SQLite if unset
        env_db_url = os.environ.get("DATABASE_URL", "").strip()
        if env_db_url:
            self.db_target = env_db_url
        elif db_path:
            self.db_target = db_path
        else:
            self.db_target = "invoiceledger.db"

        self.is_postgres = self.db_target.startswith("postgres://") or self.db_target.startswith("postgresql://")
        self.db_path = self.db_target

        if not self.is_postgres and _is_cloud_environment():
            msg = (
                f"Persistence Warning: Storage is using local SQLite database ({self.db_target}) on a cloud host. "
                "Data stored in SQLite will not persist across container restarts/redeploys. "
                "Set DATABASE_URL to a durable PostgreSQL database connection."
            )
            logger.warning(msg)
            fail_on_ephemeral = os.environ.get("FAIL_ON_EPHEMERAL_STORAGE", "").lower() in ("true", "1", "yes") or \
                                os.environ.get("REQUIRE_DURABLE_STORAGE", "").lower() in ("true", "1", "yes")
            if fail_on_ephemeral:
                raise RuntimeError(
                    f"DURABLE DATABASE REQUIRED: Storage cannot use local SQLite ({self.db_target}) "
                    "in a cloud environment when fail-fast persistence is enforced. Set DATABASE_URL."
                )

        self._init_db()

    def _get_connection(self):
        if self.is_postgres:
            if psycopg is None:
                raise ImportError("psycopg is required for PostgreSQL connections.")
            return psycopg.connect(self.db_target, row_factory=dict_row)
        else:
            conn = sqlite3.connect(self.db_target)
            conn.row_factory = sqlite3.Row
            return conn

    def _format_sql(self, sql: str) -> str:
        """Adapts SQLite parameter placeholders (?) to PostgreSQL format (%s) if connected to Postgres."""
        if self.is_postgres:
            return sql.replace("?", "%s")
        return sql

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
                total_amount DOUBLE PRECISION,
                tax_amount DOUBLE PRECISION,
                subtotal_amount DOUBLE PRECISION,
                job_id TEXT,
                job_name TEXT,
                cost_code TEXT,
                status TEXT,
                confidence_score DOUBLE PRECISION,
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
                budget_total DOUBLE PRECISION,
                cost_code_budgets TEXT,
                status TEXT,
                spreadsheet_path TEXT,
                created_at TEXT
            )
            """)
            # Migration helper if column missing in existing SQLite database
            try:
                cur.execute("ALTER TABLE jobs ADD COLUMN spreadsheet_path TEXT")
            except Exception:
                pass

            cur.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                aliases TEXT,
                contact_email TEXT,
                portal_url TEXT,
                default_job_name TEXT,
                default_cost_code TEXT,
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

        # Default vendors
        if not self.list_vendors():
            default_vendors = [
                Vendor(id="v-hd", name="The Home Depot", aliases=["Home Depot", "Home Depot Pro", "HD Supply"]),
                Vendor(id="v-abc", name="ABC Supply Co", aliases=["ABC Supply", "ABC Supply Inc"]),
                Vendor(id="v-84", name="84 Lumber", aliases=["84 Lumber Co", "Eighty Four Lumber"]),
                Vendor(id="v-ferg", name="Ferguson Enterprises", aliases=["Ferguson", "Ferguson Plumbing", "Ferguson Waterworks"]),
                Vendor(id="v-fast", name="Fastenal", aliases=["Fastenal Company", "Fastenal Co"]),
                Vendor(id="v-white", name="White Cap", aliases=["White Cap Construction Supply"]),
                Vendor(id="v-sw", name="Sherwin-Williams", aliases=["Sherwin Williams", "Sherwin-Williams Paints"]),
                Vendor(id="v-sun", name="Sunbelt Rentals", aliases=["Sunbelt Rentals Inc"]),
                Vendor(id="v-lowe", name="Lowe's Pro", aliases=["Lowes", "Lowe's"]),
            ]
            for v in default_vendors:
                self.save_vendor(v)

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
            sql = """
            INSERT INTO invoices (
                id, source_filename, vendor_name, invoice_number, invoice_date,
                due_date, po_number, total_amount, tax_amount, subtotal_amount,
                job_id, job_name, cost_code, status, confidence_score,
                file_hash, archive_path, raw_text, created_at, reviewed_at,
                notes, matched_rule_id
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?
            )
            ON CONFLICT (id) DO UPDATE SET
                source_filename = EXCLUDED.source_filename,
                vendor_name = EXCLUDED.vendor_name,
                invoice_number = EXCLUDED.invoice_number,
                invoice_date = EXCLUDED.invoice_date,
                due_date = EXCLUDED.due_date,
                po_number = EXCLUDED.po_number,
                total_amount = EXCLUDED.total_amount,
                tax_amount = EXCLUDED.tax_amount,
                subtotal_amount = EXCLUDED.subtotal_amount,
                job_id = EXCLUDED.job_id,
                job_name = EXCLUDED.job_name,
                cost_code = EXCLUDED.cost_code,
                status = EXCLUDED.status,
                confidence_score = EXCLUDED.confidence_score,
                file_hash = EXCLUDED.file_hash,
                archive_path = EXCLUDED.archive_path,
                raw_text = EXCLUDED.raw_text,
                created_at = EXCLUDED.created_at,
                reviewed_at = EXCLUDED.reviewed_at,
                notes = EXCLUDED.notes,
                matched_rule_id = EXCLUDED.matched_rule_id
            """
            cur.execute(self._format_sql(sql), (
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
            cur.execute(self._format_sql("SELECT * FROM invoices WHERE id = ?"), (inv_id,))
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
            cur.execute(self._format_sql(query), params)
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
            cur.execute(self._format_sql("DELETE FROM invoices WHERE id = ?"), (inv_id,))
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
            cur.execute(self._format_sql("SELECT * FROM invoices WHERE file_hash = ? AND status != 'rejected'"), (file_hash,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["status"] = InvoiceStatus(d["status"])
                return ExtractedInvoice(**d)

            # 2. Triplet match (Vendor, Invoice Number, Amount)
            norm_vendor = vendor_name.strip().lower()
            norm_inv = invoice_number.strip().lower()
            rounded_amt = round(total_amount, 2)

            cur.execute(self._format_sql("""
                SELECT * FROM invoices 
                WHERE LOWER(TRIM(invoice_number)) = ? 
                AND status != 'rejected'
            """), (norm_inv,))
            rows = cur.fetchall()
            for r in rows:
                d = dict(r)
                db_amount = round(float(d.get("total_amount") or 0.0), 2)
                if abs(db_amount - rounded_amt) < 0.01:
                    v_name = (d.get("vendor_name") or "").lower()
                    if norm_vendor in v_name or v_name in norm_vendor:
                        d["status"] = InvoiceStatus(d["status"])
                        return ExtractedInvoice(**d)

        return None

    # --- Jobs CRUD ---
    def save_job(self, job: Job) -> Job:
        existing = self.get_job_by_name(job.name)
        if existing and existing.id != job.id:
            job.id = existing.id
        with self._get_connection() as conn:
            cur = conn.cursor()
            sql = """
            INSERT INTO jobs (id, name, client_name, budget_total, cost_code_budgets, status, spreadsheet_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                client_name = EXCLUDED.client_name,
                budget_total = EXCLUDED.budget_total,
                cost_code_budgets = EXCLUDED.cost_code_budgets,
                status = EXCLUDED.status,
                spreadsheet_path = EXCLUDED.spreadsheet_path,
                created_at = EXCLUDED.created_at
            """
            cur.execute(self._format_sql(sql), (
                job.id,
                job.name,
                job.client_name,
                job.budget_total,
                json.dumps(job.cost_code_budgets),
                job.status,
                job.spreadsheet_path,
                job.created_at,
            ))
            conn.commit()
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM jobs WHERE id = ?"), (job_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["cost_code_budgets"] = json.loads(d.get("cost_code_budgets") or "{}")
            return Job(**d)

    def get_job_by_name(self, name: str) -> Optional[Job]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM jobs WHERE LOWER(name) = LOWER(?)"), (name.strip(),))
            row = cur.fetchone()
            if not row:
                return None
            try:
                d = dict(row)
                if not d.get("id") or not d.get("name"):
                    return None
                d["cost_code_budgets"] = json.loads(d.get("cost_code_budgets") or "{}") if isinstance(d.get("cost_code_budgets"), str) else (d.get("cost_code_budgets") or {})
                return Job(**d)
            except Exception:
                return None

    def list_jobs(self) -> List[Job]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM jobs ORDER BY name ASC"))
            rows = cur.fetchall()
            results = []
            for row in rows:
                try:
                    d = dict(row)
                    if not d.get("id") or not d.get("name"):
                        continue
                    d["cost_code_budgets"] = json.loads(d.get("cost_code_budgets") or "{}") if isinstance(d.get("cost_code_budgets"), str) else (d.get("cost_code_budgets") or {})
                    results.append(Job(**d))
                except Exception:
                    continue
            return results

    def delete_job(self, job_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("DELETE FROM jobs WHERE id = ?"), (job_id,))
            conn.commit()
            return cur.rowcount > 0

    # --- Vendors CRUD ---
    def save_vendor(self, vendor: Vendor) -> Vendor:
        existing = self.get_vendor_by_name(vendor.name)
        if existing and existing.id != vendor.id:
            vendor.id = existing.id
        with self._get_connection() as conn:
            cur = conn.cursor()
            sql = """
            INSERT INTO vendors (id, name, aliases, contact_email, portal_url, default_job_name, default_cost_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                aliases = EXCLUDED.aliases,
                contact_email = EXCLUDED.contact_email,
                portal_url = EXCLUDED.portal_url,
                default_job_name = EXCLUDED.default_job_name,
                default_cost_code = EXCLUDED.default_cost_code,
                created_at = EXCLUDED.created_at
            """
            cur.execute(self._format_sql(sql), (
                vendor.id,
                vendor.name,
                json.dumps(vendor.aliases),
                vendor.contact_email,
                vendor.portal_url,
                vendor.default_job_name,
                vendor.default_cost_code,
                vendor.created_at,
            ))
            conn.commit()
        return vendor

    def get_vendor(self, vendor_id: str) -> Optional[Vendor]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM vendors WHERE id = ?"), (vendor_id,))
            row = cur.fetchone()
            if not row:
                return None
            try:
                d = dict(row)
                if not d.get("id") or not d.get("name"):
                    return None
                d["aliases"] = json.loads(d.get("aliases") or "[]") if isinstance(d.get("aliases"), str) else (d.get("aliases") or [])
                return Vendor(**d)
            except Exception:
                return None

    def get_vendor_by_name(self, name: str) -> Optional[Vendor]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM vendors WHERE LOWER(name) = LOWER(?)"), (name.strip(),))
            row = cur.fetchone()
            if not row:
                return None
            try:
                d = dict(row)
                if not d.get("id") or not d.get("name"):
                    return None
                d["aliases"] = json.loads(d.get("aliases") or "[]") if isinstance(d.get("aliases"), str) else (d.get("aliases") or [])
                return Vendor(**d)
            except Exception:
                return None

    def list_vendors(self) -> List[Vendor]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM vendors ORDER BY name ASC"))
            rows = cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["aliases"] = json.loads(d.get("aliases") or "[]")
                results.append(Vendor(**d))
            return results

    def delete_vendor(self, vendor_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("DELETE FROM vendors WHERE id = ?"), (vendor_id,))
            conn.commit()
            return cur.rowcount > 0

    # --- Rules CRUD ---
    def save_rule(self, rule: VendorRule) -> VendorRule:
        with self._get_connection() as conn:
            cur = conn.cursor()
            sql = """
            INSERT INTO rules (id, vendor_pattern, match_type, job_name, cost_code, priority, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                vendor_pattern = EXCLUDED.vendor_pattern,
                match_type = EXCLUDED.match_type,
                job_name = EXCLUDED.job_name,
                cost_code = EXCLUDED.cost_code,
                priority = EXCLUDED.priority,
                is_active = EXCLUDED.is_active,
                created_at = EXCLUDED.created_at
            """
            cur.execute(self._format_sql(sql), (
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
            cur.execute(self._format_sql("SELECT * FROM rules WHERE id = ?"), (rule_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["is_active"] = bool(d["is_active"])
            return VendorRule(**d)

    def list_rules(self) -> List[VendorRule]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(self._format_sql("SELECT * FROM rules ORDER BY priority ASC, created_at DESC"))
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
            cur.execute(self._format_sql("DELETE FROM rules WHERE id = ?"), (rule_id,))
            conn.commit()
            return cur.rowcount > 0

    # --- Column Mappings CRUD ---
    def save_mapping(self, mapping: ColumnMappingTemplate) -> ColumnMappingTemplate:
        with self._get_connection() as conn:
            cur = conn.cursor()
            if mapping.is_default:
                cur.execute(self._format_sql("UPDATE mappings SET is_default = 0"))
            sql = """
            INSERT INTO mappings (id, template_name, columns, is_default)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                template_name = EXCLUDED.template_name,
                columns = EXCLUDED.columns,
                is_default = EXCLUDED.is_default
            """
            cur.execute(self._format_sql(sql), (
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
            cur.execute(self._format_sql("SELECT * FROM mappings WHERE id = ?"), (mapping_id,))
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
            cur.execute(self._format_sql("SELECT * FROM mappings WHERE is_default = 1 LIMIT 1"))
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
            cur.execute(self._format_sql("SELECT * FROM mappings ORDER BY is_default DESC, template_name ASC"))
            rows = cur.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["columns"] = json.loads(d["columns"])
                d["is_default"] = bool(d["is_default"])
                results.append(ColumnMappingTemplate(**d))
            return results
