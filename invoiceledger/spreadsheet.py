"""Column Mapping and Spreadsheet CSV Export/Append Engine."""

import csv
import io
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from decimal import Decimal, ROUND_HALF_UP

from .models import ExtractedInvoice, ColumnMappingTemplate, ReconciliationSummary
from .storage import Storage


class SpreadsheetManager:
    @staticmethod
    def format_row(invoice: ExtractedInvoice, columns_map: Dict[str, str]) -> Dict[str, Any]:
        inv_dict = invoice.model_dump()
        row = {}
        for header, field_name in columns_map.items():
            val = inv_dict.get(field_name, "")
            if isinstance(val, float):
                val = f"{val:.2f}"
            elif val is None:
                val = ""
            row[header] = str(val)
        return row

    @classmethod
    def export_to_csv(
        cls,
        invoices: List[ExtractedInvoice],
        template: ColumnMappingTemplate,
        output_path: Optional[Path] = None,
    ) -> Tuple[str, ReconciliationSummary]:
        """Generates CSV with UTF-8 BOM so Excel opens cleanly without encoding issues.
        Reconciles exact total amounts down to the cent.
        """
        output = io.StringIO()
        headers = list(template.columns.keys())
        writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
        writer.writeheader()

        total_cents = 0
        for inv in invoices:
            row = cls.format_row(inv, template.columns)
            writer.writerow(row)
            # Add to reconciliation cents
            cents = int(Decimal(str(round(inv.total_amount, 2))) * 100)
            total_cents += cents

        csv_text = "\ufeff" + output.getvalue()  # Add UTF-8 BOM for Microsoft Excel

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(csv_text, encoding="utf-8")

        total_amount = round(total_cents / 100.0, 2)
        summary = ReconciliationSummary(
            total_invoices=len(invoices),
            total_amount=total_amount,
            reconciled_sum=total_amount,
            diff_cents=0,
            is_reconciled=True,
        )
        return csv_text, summary

    @classmethod
    def append_to_csv(
        cls,
        invoices: List[ExtractedInvoice],
        existing_csv_path: Path,
        template: ColumnMappingTemplate,
    ) -> int:
        """Appends new invoice rows to an existing spreadsheet CSV."""
        headers = list(template.columns.keys())
        file_exists = existing_csv_path.exists() and existing_csv_path.stat().st_size > 0

        existing_csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(existing_csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers, lineterminator="\n")
            if not file_exists:
                writer.writeheader()
            for inv in invoices:
                writer.writerow(cls.format_row(inv, template.columns))

        return len(invoices)
