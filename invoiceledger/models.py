"""Data models for InvoiceLedger."""

from __future__ import annotations
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime, timezone


def get_utc_now():
    return datetime.now(timezone.utc).isoformat()


class InvoiceStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    COMMITTED = "committed"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class ExtractedInvoice(BaseModel):
    id: str
    source_filename: str
    vendor_name: str
    invoice_number: str
    invoice_date: str  # YYYY-MM-DD
    due_date: Optional[str] = None
    po_number: Optional[str] = None
    total_amount: float
    tax_amount: Optional[float] = 0.0
    subtotal_amount: Optional[float] = None
    job_id: Optional[str] = None
    job_name: Optional[str] = None
    cost_code: Optional[str] = None
    status: InvoiceStatus = InvoiceStatus.PENDING_REVIEW
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    file_hash: str
    archive_path: Optional[str] = None
    raw_text: Optional[str] = None
    created_at: str = Field(default_factory=get_utc_now)
    reviewed_at: Optional[str] = None
    notes: Optional[str] = None
    matched_rule_id: Optional[str] = None


class Job(BaseModel):
    id: str
    name: str
    client_name: str = ""
    budget_total: float = 0.0
    cost_code_budgets: Dict[str, float] = Field(default_factory=dict)
    status: str = "active"
    spreadsheet_path: Optional[str] = None
    created_at: str = Field(default_factory=get_utc_now)


class Vendor(BaseModel):
    id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    contact_email: Optional[str] = None
    portal_url: Optional[str] = None
    default_job_name: Optional[str] = None
    default_cost_code: Optional[str] = None
    created_at: str = Field(default_factory=get_utc_now)


class EmailSourceConfig(BaseModel):
    id: str = "default"
    host: str = "imap.example.com"
    port: int = 993
    username: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    use_ssl: bool = True
    protocol: str = "imap"  # imap or pop3
    search_criteria: str = "UNSEEN"  # UNSEEN, ALL, etc.
    mark_as_read: bool = True
    is_active: bool = True


class PortalSourceConfig(BaseModel):
    id: str
    name: str
    url: str
    auth_header: Optional[str] = None
    api_key: Optional[str] = None
    download_folder: Optional[str] = None
    is_active: bool = True


class VendorRule(BaseModel):
    id: str
    vendor_pattern: str
    match_type: str = "contains"  # exact, contains, regex
    job_name: str
    cost_code: str
    priority: int = 100
    is_active: bool = True
    created_at: str = Field(default_factory=get_utc_now)


class ColumnMappingTemplate(BaseModel):
    id: str
    template_name: str
    columns: Dict[str, str]  # header_name -> field_name
    is_default: bool = False


class JobRollup(BaseModel):
    job_id: str
    job_name: str
    client_name: str
    budget_total: float
    committed_spend: float
    pending_spend: float
    remaining_budget: float
    budget_utilization_pct: float
    invoice_count: int
    vendor_breakdown: Dict[str, float]
    cost_code_breakdown: Dict[str, Dict[str, float]]


class ReconciliationSummary(BaseModel):
    total_invoices: int
    total_amount: float
    reconciled_sum: float
    diff_cents: int
    is_reconciled: bool

