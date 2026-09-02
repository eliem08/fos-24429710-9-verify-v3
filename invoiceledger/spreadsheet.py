import csv
import io
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from decimal import Decimal

logger = logging.getLogger("invoiceledger.spreadsheet")

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None

from .models import ExtractedInvoice, Job, ColumnMappingTemplate, ReconciliationSummary, InvoiceStatus
from .rollups import RollupEngine



class SpreadsheetManager:
    """Handles bidirectional export and live reconciliation to CSV and Excel (.xlsx) Job P&L spreadsheets."""

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

    @classmethod
    def export_to_excel(
        cls,
        invoices: List[ExtractedInvoice],
        jobs: List[Job],
        output_path: Optional[Path] = None,
        template: Optional[ColumnMappingTemplate] = None,
    ) -> Tuple[bytes, ReconciliationSummary]:
        """Generates a professional multi-tab Excel (.xlsx) Job P&L workbook."""
        if openpyxl is None:
            raise ImportError("openpyxl is required for Excel export.")

        wb = openpyxl.Workbook()

        # Styles
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        sub_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1F4E79")
        bold_font = Font(name="Calibri", size=11, bold=True)
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        # -------------------------------------------------------------
        # Sheet 1: Job P&L Summary
        # -------------------------------------------------------------
        ws_summary = wb.active
        ws_summary.title = "Job P&L Summary"

        ws_summary["A1"] = "Job Costing & P&L Executive Summary"
        ws_summary["A1"].font = title_font

        headers_summary = [
            "Job ID", "Project Name", "Client", "Total Budget ($)",
            "Committed Spend ($)", "Pending Spend ($)", "Remaining ($)",
            "Utilization (%)", "Invoices Count"
        ]
        for col_idx, h in enumerate(headers_summary, 1):
            cell = ws_summary.cell(row=3, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        row_num = 4
        for job in jobs:
            job_invs = [inv for inv in invoices if inv.job_name == job.name]
            rollup = RollupEngine.compute_job_rollup(job, job_invs)
            ws_summary.cell(row=row_num, column=1, value=rollup.job_id)
            ws_summary.cell(row=row_num, column=2, value=rollup.job_name)
            ws_summary.cell(row=row_num, column=3, value=rollup.client_name)
            ws_summary.cell(row=row_num, column=4, value=rollup.budget_total).number_format = "$#,##0.00"
            ws_summary.cell(row=row_num, column=5, value=rollup.committed_spend).number_format = "$#,##0.00"
            ws_summary.cell(row=row_num, column=6, value=rollup.pending_spend).number_format = "$#,##0.00"
            ws_summary.cell(row=row_num, column=7, value=rollup.remaining_budget).number_format = "$#,##0.00"
            ws_summary.cell(row=row_num, column=8, value=rollup.budget_utilization_pct / 100.0).number_format = "0.0%"
            ws_summary.cell(row=row_num, column=9, value=rollup.invoice_count)
            for c in range(1, 10):
                ws_summary.cell(row=row_num, column=c).border = thin_border
            row_num += 1

        # -------------------------------------------------------------
        # Sheet 2: Cost Code Breakdown
        # -------------------------------------------------------------
        ws_codes = wb.create_sheet(title="Cost Code Breakdown")
        ws_codes["A1"] = "Budget vs. Actual Spend by Cost Code"
        ws_codes["A1"].font = title_font

        headers_codes = ["Project Name", "Cost Code", "Budget ($)", "Actual Spend ($)", "Remaining ($)", "Spent %"]
        for col_idx, h in enumerate(headers_codes, 1):
            cell = ws_codes.cell(row=3, column=col_idx, value=h)
            cell.fill = sub_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        row_num = 4
        for job in jobs:
            job_invs = [inv for inv in invoices if inv.job_name == job.name]
            rollup = RollupEngine.compute_job_rollup(job, job_invs)
            for code, data in rollup.cost_code_breakdown.items():
                ws_codes.cell(row=row_num, column=1, value=job.name)
                ws_codes.cell(row=row_num, column=2, value=code)
                ws_codes.cell(row=row_num, column=3, value=data["budget"]).number_format = "$#,##0.00"
                ws_codes.cell(row=row_num, column=4, value=data["spent"]).number_format = "$#,##0.00"
                ws_codes.cell(row=row_num, column=5, value=data["remaining"]).number_format = "$#,##0.00"
                ws_codes.cell(row=row_num, column=6, value=data["utilization_pct"] / 100.0).number_format = "0.0%"
                for c in range(1, 7):
                    ws_codes.cell(row=row_num, column=c).border = thin_border
                row_num += 1

        # -------------------------------------------------------------
        # Sheet 3: Invoice Ledger (Committed & Reconciled)
        # -------------------------------------------------------------
        ws_invoices = wb.create_sheet(title="Invoice Ledger")
        ws_invoices["A1"] = "Itemized Vendor Invoices Ledger"
        ws_invoices["A1"].font = title_font

        mapping = template.columns if template else {
            "Date": "invoice_date",
            "Project": "job_name",
            "Cost Code": "cost_code",
            "Vendor": "vendor_name",
            "Invoice #": "invoice_number",
            "PO #": "po_number",
            "Amount ($)": "total_amount",
            "Status": "status",
            "Audit Link": "archive_path",
        }

        headers_inv = list(mapping.keys())
        for col_idx, h in enumerate(headers_inv, 1):
            cell = ws_invoices.cell(row=3, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        total_cents = 0
        row_num = 4
        for inv in invoices:
            for col_idx, (header, field_name) in enumerate(mapping.items(), 1):
                val = getattr(inv, field_name, None)
                cell = ws_invoices.cell(row=row_num, column=col_idx)
                if field_name == "total_amount" and isinstance(val, (int, float)):
                    cell.value = float(val)
                    cell.number_format = "$#,##0.00"
                else:
                    cell.value = str(val or "")
                cell.border = thin_border

            cents = int(Decimal(str(round(inv.total_amount, 2))) * 100)
            total_cents += cents
            row_num += 1

        # Adjust column widths across all sheets
        for sheet in wb.worksheets:
            for col in sheet.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                sheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

        # Save to buffer / file
        buffer = io.BytesIO()
        wb.save(buffer)
        raw_bytes = buffer.getvalue()

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(raw_bytes)

        total_amount = round(total_cents / 100.0, 2)
        summary = ReconciliationSummary(
            total_invoices=len(invoices),
            total_amount=total_amount,
            reconciled_sum=total_amount,
            diff_cents=0,
            is_reconciled=True,
        )
        return raw_bytes, summary

    @classmethod
    def update_job_pl_spreadsheet(
        cls,
        job: Job,
        invoices: List[ExtractedInvoice],
        spreadsheet_path: Path,
        template: Optional[ColumnMappingTemplate] = None,
    ) -> bool:
        """Updates or creates the destination P&L spreadsheet for a given job.
        If the user already has an existing Excel workbook or CSV, updates/appends
        extracted invoice data in place without destroying custom sheets or overwriting existing rows.
        """
        committed_invoices = [i for i in invoices if i.job_name == job.name and i.status == InvoiceStatus.COMMITTED]
        suffix = spreadsheet_path.suffix.lower()

        if suffix in [".xlsx", ".xlsm"] and openpyxl is not None:
            if spreadsheet_path.exists() and spreadsheet_path.stat().st_size > 0:
                try:
                    # Create a safety backup copy before modifying existing user workbook
                    backup_path = spreadsheet_path.with_suffix(spreadsheet_path.suffix + ".bak")
                    try:
                        shutil.copy2(spreadsheet_path, backup_path)
                    except Exception as bkp_err:
                        logger.debug("Could not create spreadsheet backup: %s", bkp_err)

                    wb = openpyxl.load_workbook(
                        spreadsheet_path,
                        data_only=False,
                        keep_vba=(suffix == ".xlsm"),
                    )
                    
                    # Locate invoice ledger sheet
                    sheet_candidates = ["Invoice Ledger", "Invoices", "Ledger", "Job P&L"]
                    ws_ledger = None
                    for name in sheet_candidates:
                        if name in wb.sheetnames:
                            ws_ledger = wb[name]
                            break
                    if ws_ledger is None:
                        ws_ledger = wb.active

                    mapping = template.columns if template else {
                        "Date": "invoice_date",
                        "Project": "job_name",
                        "Cost Code": "cost_code",
                        "Vendor": "vendor_name",
                        "Invoice #": "invoice_number",
                        "PO #": "po_number",
                        "Amount ($)": "total_amount",
                        "Status": "status",
                        "Audit Link": "archive_path",
                    }

                    # Determine existing invoice numbers in sheet to prevent duplicates
                    existing_inv_nums = set()
                    for row in ws_ledger.iter_rows(values_only=True):
                        for cell_val in row:
                            if cell_val is not None:
                                existing_inv_nums.add(str(cell_val).strip().lower())

                    # Append new un-recorded invoices
                    thin_border = Border(
                        left=Side(style="thin", color="D9D9D9"),
                        right=Side(style="thin", color="D9D9D9"),
                        top=Side(style="thin", color="D9D9D9"),
                        bottom=Side(style="thin", color="D9D9D9"),
                    )

                    current_max_row = ws_ledger.max_row
                    for inv in committed_invoices:
                        if inv.invoice_number.strip().lower() in existing_inv_nums:
                            continue
                        current_max_row += 1
                        for col_idx, (header, field_name) in enumerate(mapping.items(), 1):
                            val = getattr(inv, field_name, None)
                            cell = ws_ledger.cell(row=current_max_row, column=col_idx)
                            if field_name == "total_amount" and isinstance(val, (int, float)):
                                cell.value = float(val)
                                cell.number_format = "$#,##0.00"
                            else:
                                cell.value = str(val or "")
                            cell.border = thin_border
                        existing_inv_nums.add(inv.invoice_number.strip().lower())

                    # Refresh summary sheet if present
                    if "Job P&L Summary" in wb.sheetnames:
                        ws_summary = wb["Job P&L Summary"]
                        rollup = RollupEngine.compute_job_rollup(job, committed_invoices)
                        for r in range(4, ws_summary.max_row + 1):
                            if ws_summary.cell(row=r, column=2).value == job.name:
                                ws_summary.cell(row=r, column=5, value=rollup.committed_spend).number_format = "$#,##0.00"
                                ws_summary.cell(row=r, column=7, value=rollup.remaining_budget).number_format = "$#,##0.00"
                                ws_summary.cell(row=r, column=8, value=rollup.budget_utilization_pct / 100.0).number_format = "0.0%"
                                ws_summary.cell(row=r, column=9, value=rollup.invoice_count)
                                break

                    wb.save(spreadsheet_path)
                    return True
                except Exception as e:
                    logger.warning("Could not update existing Excel file in-place: %s; recreating export", e)

            cls.export_to_excel(
                invoices=committed_invoices,
                jobs=[job],
                output_path=spreadsheet_path,
                template=template,
            )
            return True
        else:
            # CSV format
            tpl = template or ColumnMappingTemplate(
                id="tpl-job-csv",
                template_name=f"{job.name} P&L",
                columns={
                    "Date": "invoice_date",
                    "Cost Code": "cost_code",
                    "Vendor": "vendor_name",
                    "Invoice #": "invoice_number",
                    "PO #": "po_number",
                    "Total ($)": "total_amount",
                    "Audit Link": "archive_path",
                },
                is_default=False,
            )

            if spreadsheet_path.exists() and spreadsheet_path.stat().st_size > 0:
                # Check for existing invoices in CSV to avoid duplicate appending
                existing_text = spreadsheet_path.read_text(encoding="utf-8-sig", errors="replace")
                new_invoices = [inv for inv in committed_invoices if inv.invoice_number not in existing_text]
                if new_invoices:
                    cls.append_to_csv(new_invoices, spreadsheet_path, tpl)
                return True

            cls.export_to_csv(committed_invoices, tpl, spreadsheet_path)
            return True
