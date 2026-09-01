"""Duplicate Detection Guard for Invoices."""

import hashlib
from pathlib import Path
from typing import Tuple, Optional
from .models import ExtractedInvoice
from .storage import Storage


class DuplicateGuard:
    @staticmethod
    def compute_file_hash(data_or_path) -> str:
        if isinstance(data_or_path, (str, Path)):
            content = Path(data_or_path).read_bytes()
        elif isinstance(data_or_path, bytes):
            content = data_or_path
        else:
            content = str(data_or_path).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def check_duplicate(
        storage: Storage,
        invoice: ExtractedInvoice,
    ) -> Tuple[bool, Optional[ExtractedInvoice], str]:
        """Checks if the invoice is a duplicate by file hash or (vendor, invoice_num, amount) triplet."""
        dup = storage.find_duplicate(
            vendor_name=invoice.vendor_name,
            invoice_number=invoice.invoice_number,
            total_amount=invoice.total_amount,
            file_hash=invoice.file_hash,
        )
        if dup and dup.id != invoice.id:
            if dup.file_hash == invoice.file_hash:
                reason = f"Duplicate file: matches existing invoice #{dup.invoice_number} from {dup.vendor_name} (${dup.total_amount:.2f})"
            else:
                reason = f"Duplicate invoice: same vendor ({dup.vendor_name}), invoice number (#{dup.invoice_number}), and amount (${dup.total_amount:.2f})"
            return True, dup, reason

        return False, None, ""
