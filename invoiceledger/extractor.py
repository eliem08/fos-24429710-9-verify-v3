"""OCR and Field Extraction Engine for Construction Vendor Invoices."""

import re
import uuid
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from .models import ExtractedInvoice, InvoiceStatus


# Prominent construction vendor signatures & normalized names
VENDOR_CATALOG = {
    "home depot": "The Home Depot",
    "the home depot": "The Home Depot",
    "home depot pro": "The Home Depot",
    "abc supply": "ABC Supply Co",
    "abc supply co": "ABC Supply Co",
    "abc supply inc": "ABC Supply Co",
    "84 lumber": "84 Lumber",
    "eighty four lumber": "84 Lumber",
    "ferguson": "Ferguson Enterprises",
    "ferguson enterprises": "Ferguson Enterprises",
    "ferguson plumbing": "Ferguson Enterprises",
    "ferguson waterworks": "Ferguson Enterprises",
    "fastenal": "Fastenal",
    "fastenal company": "Fastenal",
    "white cap": "White Cap",
    "white cap construction": "White Cap",
    "builders firstsource": "Builders FirstSource",
    "sherwin-williams": "Sherwin-Williams",
    "sherwin williams": "Sherwin-Williams",
    "sunbelt rentals": "Sunbelt Rentals",
    "united rentals": "United Rentals",
    "lowe's": "Lowe's Pro",
    "lowes": "Lowe's Pro",
}

MONTH_MAP = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}


class Extractor:
    """Multi-pass extraction engine for invoice PDFs, images, and text."""

    def extract_text_from_file(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix in [".txt", ".log", ".json"]:
            try:
                return file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return file_path.read_text(encoding="latin-1", errors="replace")

        if suffix == ".pdf":
            if PdfReader is not None:
                try:
                    reader = PdfReader(str(file_path))
                    text_parts = []
                    for page in reader.pages:
                        t = page.extract_text()
                        if t:
                            text_parts.append(t)
                    if text_parts:
                        return "\n".join(text_parts)
                except Exception:
                    pass

            # Fallback pure-python PDF string parser
            try:
                raw_bytes = file_path.read_bytes()
                # Extract ASCII / UTF-8 strings from PDF stream
                matches = re.findall(rb"\(([^)]{3,})\)", raw_bytes)
                if matches:
                    extracted = "\n".join(m.decode("latin-1", errors="ignore") for m in matches if len(m) > 2)
                    if len(extracted.strip()) > 30:
                        return extracted
                # Plain regex on stream text
                clean = re.sub(rb"[^\x20-\x7E\n\r\t]", b" ", raw_bytes)
                return clean.decode("ascii", errors="ignore")
            except Exception:
                return ""

        # Default fallback
        try:
            return file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def normalize_vendor(self, text: str) -> Tuple[str, float]:
        text_lower = text.lower()
        # 1. Check known catalog
        for key, standard_name in VENDOR_CATALOG.items():
            if key in text_lower:
                return standard_name, 0.95

        # 2. Look for vendor header patterns (lines near top)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:8]:
            # Skip noise lines
            if any(k in line.lower() for k in ["invoice", "bill to", "ship to", "remit", "page ", "date:", "tel:", "phone", "tax id"]):
                continue
            # Pattern matching company suffix
            if re.search(r"\b(LLC|Inc\.?|Corp\.?|Co\.?|Company|Supply|Materials|Lumber|Hardware|Roofing|Plumbing|Electric|Contracting|Services)\b", line, re.I):
                clean = re.sub(r"[^A-Za-z0-9&\-\.\s]", "", line).strip()
                if len(clean) > 3:
                    return clean, 0.85

        # 3. Default to first clean header line
        if lines:
            first_line = lines[0].strip()
            if len(first_line) > 3 and len(first_line) < 50:
                return first_line, 0.60

        return "Unknown Vendor", 0.20

    def normalize_invoice_number(self, text: str) -> Tuple[str, float]:
        # Priority patterns
        patterns = [
            r"(?:Invoice\s*#|Invoice\s*Number|Invoice\s*No\.?|Invoice\s*ID|INV\s*#|INV\s*No\.?)[:\s#*-]*([A-Z0-9\-_/]{3,24})",
            r"(?:Bill\s*#|Bill\s*Number|Bill\s*No\.?)[:\s#*-]*([A-Z0-9\-_/]{3,24})",
            r"\bINV-([0-9]{3,12})\b",
            r"\b(HD-[0-9]{4,12})\b",
            r"\b(ABC-[0-9]{4,12})\b",
            r"\b(84L-[0-9]{4,12})\b",
            r"\b(FERG-[0-9]{4,12})\b",
            r"\b(FAST-[0-9]{4,12})\b",
            r"(?:Invoice)[:\s#*-]+([A-Z0-9\-_]{3,20})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                inv_num = m.group(1).strip().strip(":#*-")
                # ignore if it's a date or common word
                if inv_num and not re.match(r"^\d{4}-\d{2}-\d{2}$", inv_num) and inv_num.lower() not in ["date", "total", "amount", "number", "due"]:
                    return inv_num, 0.90

        # Generic pattern
        m = re.search(r"#\s*([A-Z0-9\-_]{4,16})", text)
        if m:
            return m.group(1).strip(), 0.70

        # Fallback generated
        return f"INV-{uuid.uuid4().hex[:8].upper()}", 0.30

    def normalize_date(self, text: str) -> Tuple[str, float]:
        # Priority date labeled patterns
        date_patterns = [
            r"(?:Invoice\s*Date|Date\s*of\s*Issue|Date\s*Billed|Date|Billed)[:\s*-]*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"(?:Invoice\s*Date|Date\s*of\s*Issue|Date\s*Billed|Date|Billed)[:\s*-]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
            r"(?:Invoice\s*Date|Date)[:\s*-]*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{1,2}/\d{1,2}/\d{4})",
            r"(\d{1,2}-\d{1,2}-\d{4})",
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.I)
            if m:
                raw_d = m.group(1).strip()
                parsed = self._parse_date_string(raw_d)
                if parsed:
                    return parsed, 0.90

        # Fallback to today
        return datetime.now(timezone.utc).strftime("%Y-%m-%d"), 0.40

    def _parse_date_string(self, raw_str: str) -> Optional[str]:
        raw_str = raw_str.replace(",", "").strip()
        # ISO: YYYY-MM-DD
        m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", raw_str)
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

        # US: MM/DD/YYYY or MM-DD-YYYY
        m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$", raw_str)
        if m:
            mo, d, y = m.groups()
            year = int(y)
            if year < 100:
                year += 2000
            return f"{year:04d}-{int(mo):02d}-{int(d):02d}"

        # Month DD YYYY e.g. August 15 2026 or Aug 15 2026
        m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$", raw_str)
        if m:
            mon_str, d, y = m.groups()
            mo_num = MONTH_MAP.get(mon_str.lower()[:3])
            if mo_num:
                return f"{int(y):04d}-{mo_num}-{int(d):02d}"

        return None

    def normalize_total(self, text: str) -> Tuple[float, float, Optional[float], Optional[float]]:
        # Look for Total, Amount Due, Balance Due, Grand Total
        patterns = [
            r"(?:Total\s*Amount|Grand\s*Total|Invoice\s*Total|Total\s*Due|Amount\s*Due|Balance\s*Due|Total\s*USD|Total)[:\s*$]*([0-9,]+\.[0-9]{2})\b",
            r"(?:Total|Due)[:\s*$]*([0-9,]+\.[0-9]{2})\b",
            r"\$\s*([0-9,]+\.[0-9]{2})",
        ]
        total_val = 0.0
        conf = 0.30
        for pat in patterns:
            matches = re.findall(pat, text, re.I)
            if matches:
                # Take the highest or explicit matched total
                for match in matches:
                    val_str = match.replace(",", "").strip()
                    try:
                        val = float(val_str)
                        if val > total_val:
                            total_val = val
                            conf = 0.90
                    except ValueError:
                        pass
                if total_val > 0.0:
                    break

        # Subtotal
        subtotal = None
        m_sub = re.search(r"(?:Subtotal|Sub\s*Total)[:\s*$]*([0-9,]+\.[0-9]{2})", text, re.I)
        if m_sub:
            try:
                subtotal = float(m_sub.group(1).replace(",", ""))
            except ValueError:
                pass

        # Tax
        tax = 0.0
        m_tax = re.search(r"(?:Sales\s*Tax|Tax)[:\s*$]*([0-9,]+\.[0-9]{2})", text, re.I)
        if m_tax:
            try:
                tax = float(m_tax.group(1).replace(",", ""))
            except ValueError:
                pass

        return round(total_val, 2), conf, subtotal, tax

    def normalize_po(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:P\.?O\.?\s*(?:#|Number|Num|No\.?)?|Purchase\s*Order\s*(?:#|No\.?)?|Job\s*PO\s*[:#]?|PO)[:\s#*-]*([A-Z0-9\-_]{3,20})",
            r"\bPO-([A-Z0-9\-_]{2,15})\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                po = m.group(1).strip().strip(":#*-")
                if po.lower() not in ["box", "date", "number", "inv", "total"]:
                    return po
        return None

    def process_file(self, file_path: Path) -> ExtractedInvoice:
        content_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(content_bytes).hexdigest()
        raw_text = self.extract_text_from_file(file_path)

        vendor, v_conf = self.normalize_vendor(raw_text)
        inv_num, num_conf = self.normalize_invoice_number(raw_text)
        inv_date, d_conf = self.normalize_date(raw_text)
        total, tot_conf, subtotal, tax = self.normalize_total(raw_text)
        po_number = self.normalize_po(raw_text)

        # Confidence calculation
        confidence = round(0.35 * v_conf + 0.25 * num_conf + 0.20 * d_conf + 0.20 * tot_conf, 2)
        if total <= 0.0:
            confidence = min(confidence, 0.40)

        inv_id = f"inv-{uuid.uuid4().hex[:10]}"

        return ExtractedInvoice(
            id=inv_id,
            source_filename=file_path.name,
            vendor_name=vendor,
            invoice_number=inv_num,
            invoice_date=inv_date,
            total_amount=total,
            tax_amount=tax,
            subtotal_amount=subtotal,
            po_number=po_number,
            status=InvoiceStatus.PENDING_REVIEW,
            confidence_score=confidence,
            file_hash=file_hash,
            raw_text=raw_text[:5000],
        )
