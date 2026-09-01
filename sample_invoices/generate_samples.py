"""Generates 20 realistic construction vendor invoice test fixtures."""

import os
from pathlib import Path

def create_raw_pdf(output_path: Path, title: str, lines: list):
    """Creates a valid, lightweight PDF file containing the text lines."""
    text_commands = []
    y = 750
    for line in lines:
        safe_line = line.replace("(", "\\(").replace(")", "\\)").replace("\\", "\\\\")
        text_commands.append(f"1 0 0 1 50 {y} Tm ({safe_line}) Tj")
        y -= 20

    stream_content = "BT /F1 11 Tf " + " ".join(text_commands) + " ET"
    stream_bytes = stream_content.encode("latin-1")
    stream_len = len(stream_bytes)

    pdf_parts = [
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin-1") + stream_bytes + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    body = b"".join(pdf_parts)
    xref_offset = len(body)

    # xref table
    xref = (
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
    )
    # Calculate exact offsets
    offsets = [0, 9, 58, 115]
    off = 115 + len(pdf_parts[2])
    offsets.append(off)
    off += len(pdf_parts[3])
    offsets.append(off)

    xref_lines = ["xref", "0 6", "0000000000 65535 f "]
    for o in offsets[1:]:
        xref_lines.append(f"{o:010d} 00000 n ")
    xref_table = "\n".join(xref_lines).encode("latin-1") + b"\n"

    trailer = (
        f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{len(body)}\n%%EOF\n"
    ).encode("latin-1")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body + xref_table + trailer)


SAMPLE_INVOICES_DATA = [
    # Vendor 1: The Home Depot Pro (4 invoices)
    {
        "filename": "home_depot_inv_101.pdf",
        "vendor": "The Home Depot Pro",
        "inv_num": "HD-984210",
        "date": "2026-08-10",
        "po": "PO-101-Framing",
        "total": "1450.75",
        "lines": [
            "THE HOME DEPOT PRO - STORE #0481",
            "Commercial Sales & Contractor Services",
            "Invoice #: HD-984210",
            "Invoice Date: 08/10/2026",
            "PO Number: PO-101-Framing",
            "Job Reference: 101 Main St Remodel",
            "--------------------------------------------------",
            "Item: 2x4x16 KD Premium Fir (Qty: 120) ... $960.00",
            "Item: 3/4in CDX Plywood Sheathing (Qty: 15) ... $490.75",
            "Subtotal: $1,450.75",
            "Sales Tax: $0.00 (Exempt Contractor)",
            "Total Amount Due: $1,450.75",
            "Payment Term: Net 30"
        ]
    },
    {
        "filename": "home_depot_inv_102.pdf",
        "vendor": "The Home Depot",
        "inv_num": "HD-984332",
        "date": "2026-08-14",
        "po": "PO-101-Hardware",
        "total": "324.50",
        "lines": [
            "The Home Depot Supply Co.",
            "Invoice Number: HD-984332",
            "Date of Issue: 2026-08-14",
            "PO #: PO-101-Hardware",
            "--------------------------------------------------",
            "Fasteners & 3in Deck Screws 25lb ... $185.00",
            "Construction Adhesive Heavy Duty ... $139.50",
            "Subtotal: $324.50",
            "Total Due: $324.50"
        ]
    },
    {
        "filename": "home_depot_inv_103.pdf",
        "vendor": "The Home Depot",
        "inv_num": "HD-984501",
        "date": "2026-08-18",
        "po": "PO-101-Drywall",
        "total": "875.20",
        "lines": [
            "THE HOME DEPOT",
            "Invoice #: HD-984501",
            "Date: 08/18/2026",
            "Purchase Order: PO-101-Drywall",
            "--------------------------------------------------",
            "1/2in Sheetrock Gypsum Panels 4x8 (Qty: 40) ... $680.00",
            "Joint Compound All-Purpose 5 Gal (Qty: 4) ... $195.20",
            "Total: $875.20"
        ]
    },
    {
        "filename": "home_depot_inv_104.pdf",
        "vendor": "The Home Depot",
        "inv_num": "HD-984680",
        "date": "2026-08-22",
        "po": "PO-101-Tools",
        "total": "450.00",
        "lines": [
            "The Home Depot Commercial",
            "Invoice No: HD-984680",
            "Billed Date: 2026-08-22",
            "PO: PO-101-Tools",
            "Diamond Blade 14in Wet/Dry ... $450.00",
            "Total Due: $450.00"
        ]
    },

    # Vendor 2: ABC Supply Co (4 invoices)
    {
        "filename": "abc_supply_inv_201.pdf",
        "vendor": "ABC Supply Co",
        "inv_num": "ABC-55102",
        "date": "2026-08-05",
        "po": "PO-101-Roofing",
        "total": "4250.00",
        "lines": [
            "ABC SUPPLY CO INC - ROOFING & SIDING",
            "Invoice #: ABC-55102",
            "Date: 08/05/2026",
            "Customer PO: PO-101-Roofing",
            "Job Site: 101 Main St Remodel",
            "--------------------------------------------------",
            "Timberline HDZ Architectural Shingles (40 sq) ... $3,600.00",
            "Synthetic Underlayment Rolls (6 rolls) ... $650.00",
            "Subtotal: $4,250.00",
            "Invoice Total: $4,250.00"
        ]
    },
    {
        "filename": "abc_supply_inv_202.pdf",
        "vendor": "ABC Supply Co",
        "inv_num": "ABC-55188",
        "date": "2026-08-12",
        "po": "PO-101-Gutters",
        "total": "1120.60",
        "lines": [
            "ABC Supply Co.",
            "Invoice Number: ABC-55188",
            "Invoice Date: 2026-08-12",
            "PO Number: PO-101-Gutters",
            "Aluminum 6in Seamless Gutter Coils ... $1,120.60",
            "Amount Due: $1,120.60"
        ]
    },
    {
        "filename": "abc_supply_inv_203.pdf",
        "vendor": "ABC Supply Co",
        "inv_num": "ABC-55240",
        "date": "2026-08-19",
        "po": "PO-101-Flashing",
        "total": "680.00",
        "lines": [
            "ABC Supply Co Inc",
            "Invoice #: ABC-55240",
            "Date: 08/19/2026",
            "PO: PO-101-Flashing",
            "Step Flashing & Drip Edge 10ft ... $680.00",
            "Total Amount: $680.00"
        ]
    },
    {
        "filename": "abc_supply_inv_204.pdf",
        "vendor": "ABC Supply Co",
        "inv_num": "ABC-55310",
        "date": "2026-08-25",
        "po": "PO-101-Vents",
        "total": "890.40",
        "lines": [
            "ABC Supply Company",
            "Invoice: ABC-55310",
            "Date: 2026-08-25",
            "PO #: PO-101-Vents",
            "Ridge Vent 4ft Sections (20 pcs) ... $890.40",
            "Total USD: $890.40"
        ]
    },

    # Vendor 3: 84 Lumber (4 invoices)
    {
        "filename": "84_lumber_inv_301.pdf",
        "vendor": "84 Lumber",
        "inv_num": "84L-77401",
        "date": "2026-08-02",
        "po": "PO-310-Trusses",
        "total": "8450.00",
        "lines": [
            "84 LUMBER COMPANY - BUILDING MATERIALS",
            "Invoice #: 84L-77401",
            "Date: 08/02/2026",
            "Purchase Order #: PO-310-Trusses",
            "Job: 310 Elm Creek New Build",
            "--------------------------------------------------",
            "Engineered Roof Trusses 32ft Span (Qty: 24) ... $6,800.00",
            "LVL Beam 1-3/4 x 11-7/8 (Qty: 4) ... $1,650.00",
            "Total Amount Due: $8,450.00"
        ]
    },
    {
        "filename": "84_lumber_inv_302.pdf",
        "vendor": "84 Lumber",
        "inv_num": "84L-77480",
        "date": "2026-08-09",
        "po": "PO-310-Subfloor",
        "total": "3120.00",
        "lines": [
            "84 Lumber Co",
            "Invoice No: 84L-77480",
            "Invoice Date: 2026-08-09",
            "PO: PO-310-Subfloor",
            "Advantech Subfloor Panels 3/4in (Qty: 60) ... $3,120.00",
            "Grand Total: $3,120.00"
        ]
    },
    {
        "filename": "84_lumber_inv_303.pdf",
        "vendor": "84 Lumber",
        "inv_num": "84L-77545",
        "date": "2026-08-16",
        "po": "PO-310-Studs",
        "total": "2450.80",
        "lines": [
            "84 Lumber",
            "Invoice #: 84L-77545",
            "Date: 08/16/2026",
            "Purchase Order: PO-310-Studs",
            "2x6x10 SPF Studs (Qty: 250) ... $2,450.80",
            "Balance Due: $2,450.80"
        ]
    },
    {
        "filename": "84_lumber_inv_304.pdf",
        "vendor": "84 Lumber",
        "inv_num": "84L-77612",
        "date": "2026-08-24",
        "po": "PO-310-Windows",
        "total": "5890.00",
        "lines": [
            "84 LUMBER BUILDING SOLUTIONS",
            "Invoice Number: 84L-77612",
            "Date: 2026-08-24",
            "PO Number: PO-310-Windows",
            "Vinyl Low-E Double Hung Windows (Qty: 14) ... $5,890.00",
            "Total Amount: $5,890.00"
        ]
    },

    # Vendor 4: Ferguson Enterprises (4 invoices)
    {
        "filename": "ferguson_inv_401.pdf",
        "vendor": "Ferguson Enterprises",
        "inv_num": "FERG-10940",
        "date": "2026-08-04",
        "po": "PO-204-RoughPlumbing",
        "total": "3640.50",
        "lines": [
            "FERGUSON ENTERPRISES - PLUMBING SUPPLY",
            "Invoice #: FERG-10940",
            "Invoice Date: 08/04/2026",
            "Customer PO: PO-204-RoughPlumbing",
            "Job Name: 204 Pine Ridge Commercial",
            "--------------------------------------------------",
            "PEX-A Tubing 3/4in 500ft ... $820.50",
            "Cast Iron No-Hub Drain Pipe & Fittings ... $2,820.00",
            "Invoice Total: $3,640.50"
        ]
    },
    {
        "filename": "ferguson_inv_402.pdf",
        "vendor": "Ferguson Enterprises",
        "inv_num": "FERG-10992",
        "date": "2026-08-11",
        "po": "PO-204-Valves",
        "total": "1280.00",
        "lines": [
            "Ferguson Enterprises Inc",
            "Invoice No: FERG-10992",
            "Date: 2026-08-11",
            "PO: PO-204-Valves",
            "Commercial Ball Valves & Backflow Preventer ... $1,280.00",
            "Amount Due: $1,280.00"
        ]
    },
    {
        "filename": "ferguson_inv_403.pdf",
        "vendor": "Ferguson Enterprises",
        "inv_num": "FERG-11045",
        "date": "2026-08-17",
        "po": "PO-204-WaterHeater",
        "total": "2950.75",
        "lines": [
            "FERGUSON WATERWORKS",
            "Invoice #: FERG-11045",
            "Date: 08/17/2026",
            "Purchase Order: PO-204-WaterHeater",
            "Commercial 100-Gal Gas Water Heater ... $2,950.75",
            "Total Due: $2,950.75"
        ]
    },
    {
        "filename": "ferguson_inv_404.pdf",
        "vendor": "Ferguson Enterprises",
        "inv_num": "FERG-11118",
        "date": "2026-08-26",
        "po": "PO-204-Fixtures",
        "total": "1840.00",
        "lines": [
            "Ferguson Plumbing Supplies",
            "Invoice Number: FERG-11118",
            "Date: 2026-08-26",
            "PO #: PO-204-Fixtures",
            "Sensor Faucets & Flushometers (Qty: 6) ... $1,840.00",
            "Total Amount: $1,840.00"
        ]
    },

    # Vendor 5: Fastenal Company (4 invoices)
    {
        "filename": "fastenal_inv_501.pdf",
        "vendor": "Fastenal",
        "inv_num": "FAST-6601",
        "date": "2026-08-07",
        "po": "PO-204-Conduit",
        "total": "1420.30",
        "lines": [
            "FASTENAL COMPANY - INDUSTRIAL & ELECTRICAL",
            "Invoice #: FAST-6601",
            "Invoice Date: 08/07/2026",
            "PO Number: PO-204-Conduit",
            "Job Site: 204 Pine Ridge Commercial",
            "--------------------------------------------------",
            "EMT Conduit 3/4in 10ft (Qty: 100) ... $920.30",
            "Strut Channel & Clamps ... $500.00",
            "Total Amount Due: $1,420.30"
        ]
    },
    {
        "filename": "fastenal_inv_502.pdf",
        "vendor": "Fastenal",
        "inv_num": "FAST-6644",
        "date": "2026-08-13",
        "po": "PO-204-Wire",
        "total": "2150.00",
        "lines": [
            "Fastenal Supply",
            "Invoice No: FAST-6644",
            "Date: 2026-08-13",
            "PO: PO-204-Wire",
            "THHN Copper Wire 12 AWG 1000ft (Qty: 4) ... $2,150.00",
            "Amount Due: $2,150.00"
        ]
    },
    {
        "filename": "fastenal_inv_503.pdf",
        "vendor": "Fastenal",
        "inv_num": "FAST-6710",
        "date": "2026-08-20",
        "po": "PO-204-Panels",
        "total": "3490.50",
        "lines": [
            "FASTENAL",
            "Invoice #: FAST-6710",
            "Date: 08/20/2026",
            "Purchase Order: PO-204-Panels",
            "200A 3-Phase Main Distribution Panel ... $3,490.50",
            "Total: $3,490.50"
        ]
    },
    {
        "filename": "fastenal_inv_504.pdf",
        "vendor": "Fastenal",
        "inv_num": "FAST-6788",
        "date": "2026-08-27",
        "po": "PO-204-Lighting",
        "total": "1780.00",
        "lines": [
            "Fastenal Company",
            "Invoice Number: FAST-6788",
            "Billed Date: 2026-08-27",
            "PO #: PO-204-Lighting",
            "2x4 LED Troffer Fixtures 4000K (Qty: 20) ... $1,780.00",
            "Total Amount: $1,780.00"
        ]
    },
]

def generate_all_samples(base_dir: Path):
    base_dir.mkdir(parents=True, exist_ok=True)
    for inv_data in SAMPLE_INVOICES_DATA:
        pdf_path = base_dir / inv_data["filename"]
        create_raw_pdf(pdf_path, inv_data["vendor"], inv_data["lines"])
        # Also write text version
        txt_path = base_dir / (pdf_path.stem + ".txt")
        txt_path.write_text("\n".join(inv_data["lines"]), encoding="utf-8")
        print(f"Generated sample invoice: {inv_data['filename']}")

if __name__ == "__main__":
    out_dir = Path(__file__).parent
    generate_all_samples(out_dir)
