# InvoiceLedger 📐

> **Automated vendor invoice intake, OCR field extraction, job costing rules, and P&L spreadsheet reconciler for small-to-mid-size contractors.**

---

## The Problem
Small construction firms and general contractors receive hundreds of vendor invoices monthly across email and supplier portals (Home Depot, ABC Supply, 84 Lumber, Ferguson, Fastenal). Office admins manually download, rename, and re-key invoice amounts into per-job Excel or Google Sheets P&L spreadsheets.

This manual process is:
- **Slow & error-prone**: Re-keying amounts causes spreadsheet formulas and job costing to misalign.
- **Delayed job-cost visibility**: Project managers only see cost overruns weeks after the invoice was received.
- **Messy record-keeping**: PDF receipts are scattered across email inboxes and desktop download folders.

**InvoiceLedger** automates the entire intake-to-spreadsheet pipeline in **under 30 seconds per invoice** with 100% cent-exact reconciliation guarantees.

---

## Key Features

1. **Multi-Channel Invoice Intake**:
   - Drag & drop PDF, scanned images (PNG/JPG), or plain text receipts.
   - Email inbox / forwarding address ingestion (parses `.eml` attachments automatically).
   - Batch directory scanning.

2. **Accurate OCR & Field Extraction Engine**:
   - Automatically extracts **Vendor Name**, **Invoice #**, **Date**, **Total Amount ($)**, and **PO Number** with >=90% field accuracy.
   - Built-in vendor catalog normalization for major construction suppliers (The Home Depot, ABC Supply Co, 84 Lumber, Ferguson Enterprises, Fastenal, White Cap, Builders FirstSource, Sherwin-Williams, etc.).
   - Confidence scoring on every extracted field.

3. **Vendor-to-Job & Cost-Code Automation Rules**:
   - Configurable rules: `Vendor Pattern` -> `Target Job` & `Cost Code` (e.g., `Home Depot` -> `101 Main St Remodel`, `06-Framing`).
   - **Auto-Learning Engine**: Whenever a user assigns or corrects a job/cost code in the review queue, 1-click saves it as a persistent rule for future invoices.

4. **Human Review Screen**:
   - Side-by-side verification of extracted fields with invoice preview before commit.
   - 1-click Quick Approve or inline field editor.
   - Less than 30 seconds per invoice workflow.

5. **Duplicate Guard**:
   - SHA-256 file fingerprinting and `(Vendor, Invoice #, Amount)` triplet matching.
   - Automatically detects and prevents duplicate invoice entries from corrupting P&L spreadsheets.

6. **Organized File Archive**:
   - Automatically archives files into clean directory hierarchy:
     `archive/{job_folder}/{vendor_folder}/{YYYY-MM-DD}_{invoice_num}_{filename}`
   - Maintains clickable local file audit links for every row.

7. **Configurable Spreadsheet Column Mapper & 1-Click Export**:
   - User-defined column layout templates (Contractor P&L, QuickBooks import, Job Costing Detailed).
   - Exports CSV with UTF-8 BOM for seamless opening in Microsoft Excel and Google Sheets without prompt or encoding corruption.
   - **Exact Cent-Level Reconciliation Guarantee**: Validates that exported spreadsheet sum matches the exact cents of source invoices ($0.00 difference).
   - Direct append to existing spreadsheet files without overwriting existing data.

8. **Real-Time Job-Level P&L Rollups**:
   - Instant spend-to-date vs budget limits per project.
   - Cost code breakdown with utilization percentages.
   - Vendor spend distribution.

---

## Installation

```bash
# Clone or navigate to the repository
cd candidate_24429710_9_looking-for-a-way-to-automate-downloading-and-or

# Install dependencies
pip install -r requirements.txt

# (Optional) Install editable package
pip install -e .
```

---

## Quick Start CLI

```bash
# 1. Scan and ingest a folder of invoice PDFs
invoiceledger scan sample_invoices/

# 2. View pending review queue
invoiceledger review

# 3. Commit an invoice with auto-learned rule
invoiceledger commit <invoice_id> --job "101 Main St Remodel" --cost-code "06-Framing" --save-rule

# 4. View real-time job rollups and budget spend
invoiceledger jobs

# 5. Export committed ledger to Excel CSV
invoiceledger export --output "Job_Costing_PL.csv"

# 6. Launch Web Dashboard UI
invoiceledger serve --port 8000
```

---

## Web Dashboard

Start the web server with `uvicorn app:app --host 0.0.0.0 --port 8000` or `invoiceledger serve`:
- Navigate to `http://localhost:8000` in any modern browser.
- **Intake**: Drag and drop PDF invoices directly onto the dropzone.
- **Review**: Review extracted fields, adjust job/cost-code, and approve with 1-click.
- **Job Rollups**: Track budgets, committed spend, and cost codes in real-time.
- **Committed Ledger**: Filter by job and export customized CSV reports matching your spreadsheet columns.
- **Rules Engine**: Manage vendor automation rules.

---

## Acceptance Tests & Verification

Run the comprehensive test suite with `pytest`:

```bash
pytest -v
```

All 9 test suites verify:
- Field extraction accuracy >= 90% across 20+ invoices from 5 vendors.
- Rule auto-learning from review corrections.
- Duplicate detection by hash and field triplet.
- Exact cent-level spreadsheet reconciliation.
- Real-time job rollups in < 30 seconds.
- File archiving and audit links.
- Email attachment ingestion.
- REST API and CLI commands.

---

## License
MIT License.
