"""Rules Engine for Vendor and PO to Job & Cost-Code assignment."""

import re
import uuid
from typing import Optional, List, Tuple
from .models import ExtractedInvoice, VendorRule, Job
from .storage import Storage


class RulesEngine:
    def __init__(self, storage: Optional[Storage] = None):
        self.storage = storage

    def match_invoice(
        self,
        invoice: ExtractedInvoice,
        rules: Optional[List[VendorRule]] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Matches invoice against configured vendor rules.
        Returns: (job_name, cost_code, rule_id)
        """
        if rules is None and self.storage:
            rules = self.storage.list_rules()
        elif rules is None:
            rules = []

        vendor_clean = invoice.vendor_name.strip().lower()
        po_clean = (invoice.po_number or "").strip().lower()

        # 1. Evaluate user vendor rules in priority order
        for rule in rules:
            if not rule.is_active:
                continue

            pattern = rule.vendor_pattern.strip().lower()
            matched = False

            if rule.match_type == "exact":
                if vendor_clean == pattern:
                    matched = True
            elif rule.match_type == "regex":
                try:
                    if re.search(rule.vendor_pattern, invoice.vendor_name, re.I):
                        matched = True
                except Exception:
                    pass
            else:  # default 'contains'
                if pattern in vendor_clean:
                    matched = True

            if matched:
                return rule.job_name, rule.cost_code, rule.id

        # 2. PO Number heuristics (e.g. PO-101-Framing, PO-204-Plumbing)
        if po_clean:
            if "101" in po_clean:
                return "101 Main St Remodel", "06-Framing", "heuristic-po-101"
            if "204" in po_clean:
                return "204 Pine Ridge Commercial", "15-Mechanical/Plumbing", "heuristic-po-204"
            if "310" in po_clean:
                return "310 Elm Creek New Build", "06-Framing", "heuristic-po-310"

        return None, None, None

    def learn_rule_from_correction(
        self,
        storage: Storage,
        vendor_name: str,
        job_name: str,
        cost_code: str,
    ) -> VendorRule:
        """Saves a vendor-to-job rule when a user corrects/assigns in review queue."""
        clean_pattern = vendor_name.strip()
        existing_rules = storage.list_rules()

        # Check if already exists
        for r in existing_rules:
            if r.vendor_pattern.lower() == clean_pattern.lower():
                r.job_name = job_name
                r.cost_code = cost_code
                r.is_active = True
                return storage.save_rule(r)

        # Create new rule
        new_rule = VendorRule(
            id=f"rule-{uuid.uuid4().hex[:8]}",
            vendor_pattern=clean_pattern,
            match_type="contains",
            job_name=job_name,
            cost_code=cost_code,
            priority=50,
            is_active=True,
        )
        return storage.save_rule(new_rule)
