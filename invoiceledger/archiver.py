"""File Archiving and Audit Organization for Invoices."""

import re
import shutil
from pathlib import Path
from typing import Optional, Tuple


def slugify(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "-", text.strip().lower()).strip("-")
    return clean or "unknown"


class Archiver:
    def __init__(self, base_dir: str = "archive"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def archive_invoice_file(
        self,
        source_path: Path,
        job_name: Optional[str],
        vendor_name: str,
        invoice_date: str,
        invoice_number: str,
    ) -> Tuple[str, Path]:
        """Organizes file into: archive/{job_folder}/{vendor_folder}/{date}_{invoice_num}_{filename}
        Returns relative archive path string and absolute Path.
        """
        job_slug = slugify(job_name) if job_name else "unassigned-job"
        vendor_slug = slugify(vendor_name)
        date_slug = slugify(invoice_date)
        inv_slug = slugify(invoice_number)

        target_dir = self.base_dir / job_slug / vendor_slug
        target_dir.mkdir(parents=True, exist_ok=True)

        original_name = slugify(source_path.stem)
        ext = source_path.suffix.lower() or ".pdf"
        target_filename = f"{date_slug}_{inv_slug}_{original_name}{ext}"
        target_path = target_dir / target_filename

        # Copy file if source exists
        if source_path.exists() and source_path.resolve() != target_path.resolve():
            shutil.copy2(source_path, target_path)
        elif not target_path.exists() and source_path.exists():
            shutil.copy2(source_path, target_path)

        # Return clean relative posix path
        rel_path = target_path.as_posix()
        return rel_path, target_path
