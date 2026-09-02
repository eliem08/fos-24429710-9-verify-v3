"""Intake Manager for Automated Email, Portal, File, Folder, and Hot-Folder Ingestion."""

import email
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from .models import ExtractedInvoice, InvoiceStatus, EmailSourceConfig, PortalSourceConfig
from .storage import Storage
from .extractor import Extractor
from .rules_engine import RulesEngine
from .duplicate_guard import DuplicateGuard
from .archiver import Archiver
from .email_fetcher import EmailFetcher
from .portal_fetcher import PortalFetcher
from .spreadsheet import SpreadsheetManager


class IntakeManager:
    """End-to-end ingestion manager connecting automated fetching, OCR extraction,
    rules routing, deduplication, durable archiving, and live P&L spreadsheet sync.
    """

    def __init__(
        self,
        storage: Storage,
        extractor: Optional[Extractor] = None,
        rules_engine: Optional[RulesEngine] = None,
        archiver: Optional[Archiver] = None,
        email_fetcher: Optional[EmailFetcher] = None,
        portal_fetcher: Optional[PortalFetcher] = None,
    ):
        self.storage = storage
        self.extractor = extractor or Extractor()
        self.extractor.load_vendors_from_storage(self.storage)
        self.rules_engine = rules_engine or RulesEngine(storage)
        self.archiver = archiver or Archiver()
        self.email_fetcher = email_fetcher or EmailFetcher()
        self.portal_fetcher = portal_fetcher or PortalFetcher()

    def process_single_file(
        self,
        file_path: Path,
        auto_commit_if_confident: bool = False,
        auto_sync_spreadsheet: bool = True,
    ) -> Tuple[Optional[ExtractedInvoice], bool, str]:
        """Ingests, extracts, checks duplicates, applies rules, archives, and saves invoice."""
        # 1. Extract invoice fields
        try:
            invoice = self.extractor.process_file(file_path)
        except Exception as e:
            return None, False, f"Extraction failed: {str(e)}"

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

        # 4. Archiving (Local or S3/Blob storage)
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

        # 7. Live P&L Spreadsheet sync if committed and job spreadsheet configured
        if auto_sync_spreadsheet and saved.status == InvoiceStatus.COMMITTED and saved.job_name:
            job_obj = self.storage.get_job_by_name(saved.job_name)
            if job_obj and job_obj.spreadsheet_path:
                try:
                    all_job_invs = self.storage.list_invoices(job_name=saved.job_name)
                    SpreadsheetManager.update_job_pl_spreadsheet(
                        job=job_obj,
                        invoices=all_job_invs,
                        spreadsheet_path=Path(job_obj.spreadsheet_path),
                    )
                except Exception:
                    pass

        return saved, True, "Successfully processed"

    def process_directory(
        self,
        dir_path: Path,
        auto_commit_if_confident: bool = False,
    ) -> List[ExtractedInvoice]:
        results = []
        if not dir_path.is_dir():
            return results
        for f in dir_path.glob("**/*"):
            if f.is_file() and f.suffix.lower() in [".pdf", ".txt", ".png", ".jpg", ".jpeg", ".tiff"]:
                inv, ok, _ = self.process_single_file(f, auto_commit_if_confident=auto_commit_if_confident)
                if inv:
                    results.append(inv)
        return results

    def process_email_eml(
        self,
        eml_content: bytes,
        auto_commit_if_confident: bool = False,
    ) -> List[ExtractedInvoice]:
        """Extracts attachments from an .eml email file and processes them."""
        msg = email.message_from_bytes(eml_content)
        temp_dir = Path("temp_email_attachments")
        temp_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for part in msg.walk():
            fn = part.get_filename()
            if fn and any(fn.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".jpeg", ".txt", ".tiff"]):
                payload = part.get_payload(decode=True)
                if payload:
                    temp_file = temp_dir / fn
                    temp_file.write_bytes(payload)
                    inv, ok, _ = self.process_single_file(temp_file, auto_commit_if_confident=auto_commit_if_confident)
                    if inv:
                        results.append(inv)

        return results

    def fetch_and_process_emails(
        self,
        config: Optional[EmailSourceConfig] = None,
        target_dir: Optional[Path] = None,
        auto_commit_if_confident: bool = True,
    ) -> List[ExtractedInvoice]:
        """Connects to configured IMAP/POP3 mailbox, downloads new invoice attachments, and ingests them.
        Only marks messages as \\Seen after all attachments have been successfully processed.
        """
        fetcher = EmailFetcher(config) if config else EmailFetcher()
        
        def _process(file_path: Path) -> Optional[ExtractedInvoice]:
            inv, ok, reason = self.process_single_file(
                file_path=file_path,
                auto_commit_if_confident=auto_commit_if_confident,
            )
            return inv

        return fetcher.fetch_and_process_messages(_process, target_dir=target_dir)

    def fetch_and_process_portals(
        self,
        portal_configs: Optional[List[PortalSourceConfig]] = None,
        target_dir: Optional[Path] = None,
        auto_commit_if_confident: bool = True,
    ) -> List[ExtractedInvoice]:
        """Polls vendor portals/APIs, downloads invoices, and ingests them."""
        fetcher = PortalFetcher(portal_configs) if portal_configs else self.portal_fetcher
        downloaded = fetcher.fetch_all(target_dir=target_dir)

        results = []
        for file_path, meta in downloaded:
            inv, ok, reason = self.process_single_file(
                file_path=file_path,
                auto_commit_if_confident=auto_commit_if_confident,
            )
            if inv:
                results.append(inv)

        return results

    def poll_and_ingest(
        self,
        watch_dirs: Optional[List[Path]] = None,
        email_config: Optional[EmailSourceConfig] = None,
        portal_configs: Optional[List[PortalSourceConfig]] = None,
        auto_commit_if_confident: bool = True,
    ) -> Dict[str, Any]:
        """Executes a full automated intake cycle:
        1. Downloads from Vendor Emails (IMAP/POP3)
        2. Downloads from Vendor Portals/APIs
        3. Scans Hot Watch Folders
        4. Reconciles and synchronizes Job P&L Spreadsheets
        """
        all_processed: List[ExtractedInvoice] = []

        # 1. Email Ingestion
        try:
            email_invs = self.fetch_and_process_emails(
                config=email_config,
                auto_commit_if_confident=auto_commit_if_confident,
            )
            all_processed.extend(email_invs)
        except Exception:
            pass

        # 2. Portal Ingestion
        try:
            portal_invs = self.fetch_and_process_portals(
                portal_configs=portal_configs,
                auto_commit_if_confident=auto_commit_if_confident,
            )
            all_processed.extend(portal_invs)
        except Exception:
            pass

        # 3. Watch Directories
        if watch_dirs:
            for d in watch_dirs:
                if d.exists() and d.is_dir():
                    dir_invs = self.process_directory(
                        dir_path=d,
                        auto_commit_if_confident=auto_commit_if_confident,
                    )
                    all_processed.extend(dir_invs)

        committed_count = sum(1 for i in all_processed if i.status == InvoiceStatus.COMMITTED)
        pending_count = sum(1 for i in all_processed if i.status == InvoiceStatus.PENDING_REVIEW)
        dup_count = sum(1 for i in all_processed if i.status == InvoiceStatus.DUPLICATE)

        return {
            "total_processed": len(all_processed),
            "committed_count": committed_count,
            "pending_count": pending_count,
            "duplicate_count": dup_count,
            "invoices": all_processed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
