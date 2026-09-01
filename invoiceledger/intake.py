"""Intake Manager for File, Folder, Drag-and-Drop, and Email Ingestion."""

import email
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from .models import ExtractedInvoice, InvoiceStatus
from .storage import Storage
from .extractor import Extractor
from .rules_engine import RulesEngine
from .duplicate_guard import DuplicateGuard
from .archiver import Archiver


class IntakeManager:
    def __init__(
        self,
        storage: Storage,
        extractor: Optional[Extractor] = None,
        rules_engine: Optional[RulesEngine] = None,
        archiver: Optional[Archiver] = None,
    ):
        self.storage = storage
        self.extractor = extractor or Extractor()
        self.rules_engine = rules_engine or RulesEngine(storage)
        self.archiver = archiver or Archiver()

    def process_single_file(
        self,
        file_path: Path,
        auto_commit_if_confident: bool = False,
    ) -> Tuple[ExtractedInvoice, bool, str]:
        """Ingests, extracts, checks duplicates, applies rules, archives, and saves invoice."""
        # 1. Extract invoice fields
        invoice = self.extractor.process_file(file_path)

        # 2. Duplicate Guard
        is_dup, orig_inv, reason = DuplicateGuard.check_duplicate(self.storage, invoice)
        if is_dup:
            invoice.status = InvoiceStatus.DUPLICATE
            invoice.notes = reason
            self.storage.save_invoice(invoice)
            return invoice, False, reason

        # 3. Rules Engine (Vendor/PO matching)
        job_name, cost_code, rule_id = self.rules_engine.match_invoice(invoice)
        if job_name:
            invoice.job_name = job_name
            invoice.cost_code = cost_code
            invoice.matched_rule_id = rule_id
            job_obj = self.storage.get_job_by_name(job_name)
            if job_obj:
                invoice.job_id = job_obj.id

        # 4. Archiving
        rel_archive_path, _ = self.archiver.archive_invoice_file(
            source_path=file_path,
            job_name=invoice.job_name,
            vendor_name=invoice.vendor_name,
            invoice_date=invoice.invoice_date,
            invoice_number=invoice.invoice_number,
        )
        invoice.archive_path = rel_archive_path

        # 5. Status Decision: auto-commit if confident and matched, otherwise review queue
        if auto_commit_if_confident and invoice.job_name and invoice.confidence_score >= 0.85:
            invoice.status = InvoiceStatus.COMMITTED
            invoice.reviewed_at = datetime.now(timezone.utc).isoformat()
        else:
            invoice.status = InvoiceStatus.PENDING_REVIEW

        # 6. Save to storage
        saved = self.storage.save_invoice(invoice)
        return saved, True, "Successfully processed"

    def process_directory(self, dir_path: Path) -> List[ExtractedInvoice]:
        results = []
        if not dir_path.is_dir():
            return results
        for f in dir_path.glob("**/*"):
            if f.is_file() and f.suffix.lower() in [".pdf", ".txt", ".png", ".jpg", ".jpeg"]:
                inv, ok, _ = self.process_single_file(f)
                results.append(inv)
        return results

    def process_email_eml(self, eml_content: bytes) -> List[ExtractedInvoice]:
        """Extracts attachments from an .eml email file and processes them."""
        msg = email.message_from_bytes(eml_content)
        temp_dir = Path("temp_email_attachments")
        temp_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for part in msg.walk():
            fn = part.get_filename()
            if fn and any(fn.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".txt"]):
                payload = part.get_payload(decode=True)
                if payload:
                    temp_file = temp_dir / fn
                    temp_file.write_bytes(payload)
                    inv, ok, _ = self.process_single_file(temp_file)
                    results.append(inv)

        return results
