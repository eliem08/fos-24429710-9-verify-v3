"""File Archiving and Audit Organization for Invoices supporting Local & S3/Blob Storage."""

import os
import re
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("invoiceledger.archiver")

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = None


def slugify(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "-", text.strip().lower()).strip("-")
    return clean or "unknown"


def _is_cloud_environment() -> bool:
    """Detects whether code is executing in a PaaS or container cloud environment."""
    cloud_indicators = [
        "RENDER", "DYNO", "FLY_APP_NAME", "FLY_ALLOC_ID", "RAILWAY_ENVIRONMENT",
        "RAILWAY_STATIC_URL", "HEROKU_APP_ID", "HEROKU_DYNO_ID", "VERCEL",
        "AWS_LAMBDA_FUNCTION_NAME", "K_SERVICE", "KOYEB_APP_NAME",
        "CONTAINER", "DOCKER_CONTAINER", "KUBERNETES_SERVICE_HOST",
        "COOLIFY_APP_ID", "CAPROVER_APP_NAME"
    ]
    if any(os.environ.get(k) for k in cloud_indicators):
        return True
    env_name = os.environ.get("ENVIRONMENT", os.environ.get("ENV", os.environ.get("NODE_ENV", ""))).lower().strip()
    if env_name in ("production", "prod", "staging"):
        return True
    return False


class Archiver:
    """Manages audit-ready invoice archiving to local filesystem and durable S3 / Cloud Blob storage."""

    def __init__(
        self,
        base_dir: str = "archive",
        backend: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_endpoint_url: Optional[str] = None,
        s3_region: Optional[str] = None,
    ):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Storage backend resolution
        env_backend = os.environ.get("STORAGE_BACKEND", "").lower().strip()
        self.s3_bucket = s3_bucket or os.environ.get("S3_BUCKET") or os.environ.get("AWS_S3_BUCKET")
        self.backend = (backend or env_backend or ("s3" if self.s3_bucket else "local")).lower()

        self.s3_endpoint_url = s3_endpoint_url or os.environ.get("S3_ENDPOINT_URL")
        self.s3_region = s3_region or os.environ.get("AWS_REGION", "us-east-1")
        self._s3_client = None

        if self.backend == "local" and _is_cloud_environment():
            msg = (
                f"CRITICAL PERSISTENCE WARNING: Archiver is configured with local ephemeral storage ('{self.base_dir}') on a cloud host. "
                "Archived invoice documents will be wiped on restart/redeploy. "
                "Set STORAGE_BACKEND=s3 and configure S3_BUCKET (or AWS_S3_BUCKET) for durable cloud storage."
            )
            logger.warning(msg)
            fail_on_ephemeral = os.environ.get("FAIL_ON_EPHEMERAL_STORAGE", "").lower() in ("true", "1", "yes") or \
                                os.environ.get("REQUIRE_DURABLE_STORAGE", "").lower() in ("true", "1", "yes")
            if fail_on_ephemeral:
                raise RuntimeError(
                    f"DURABLE STORAGE REQUIRED: Archiver cannot use local ephemeral directory ('{self.base_dir}') "
                    "in a cloud environment when fail-fast persistence is enforced. Set STORAGE_BACKEND=s3 and configure S3_BUCKET."
                )

    def _get_s3_client(self):
        if self._s3_client is not None:
            return self._s3_client
        if boto3 is None:
            raise ImportError("boto3 is required for S3 storage backend.")
        
        session_kwargs = {}
        access_key = os.environ.get("S3_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("S3_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key
        if self.s3_region:
            session_kwargs["region_name"] = self.s3_region

        client_kwargs = {}
        if self.s3_endpoint_url:
            client_kwargs["endpoint_url"] = self.s3_endpoint_url

        session = boto3.Session(**session_kwargs)
        self._s3_client = session.client("s3", **client_kwargs)
        return self._s3_client

    def archive_invoice_file(
        self,
        source_path: Path,
        job_name: Optional[str],
        vendor_name: str,
        invoice_date: str,
        invoice_number: str,
    ) -> Tuple[str, Path]:
        """Organizes file into: archive/{job_folder}/{vendor_folder}/{date}_{invoice_num}_{filename}
        Guarantees uniqueness and prevents overwrite collisions for distinct files.
        If S3 backend is enabled, uploads to S3 bucket and returns s3:// URI or key.
        Returns (archive_path_str, local_target_path).
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

        source_bytes = source_path.read_bytes() if source_path.exists() else None
        source_hash = hashlib.sha256(source_bytes).hexdigest() if source_bytes else ""

        # Collision detection: if target already exists with DIFFERENT content, add uniqueness suffix
        if target_path.exists() and target_path.resolve() != source_path.resolve():
            if source_bytes is None:
                counter = 1
                while target_path.exists():
                    target_filename = f"{date_slug}_{inv_slug}_{original_name}_{counter}{ext}"
                    target_path = target_dir / target_filename
                    counter += 1
            else:
                target_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                if target_hash != source_hash:
                    counter = 1
                    while target_path.exists():
                        target_h = hashlib.sha256(target_path.read_bytes()).hexdigest()
                        if target_h == source_hash:
                            break
                        target_filename = f"{date_slug}_{inv_slug}_{original_name}_{counter}{ext}"
                        target_path = target_dir / target_filename
                        counter += 1

        # Copy file if source exists and target not identical
        if source_path.exists() and source_path.resolve() != target_path.resolve():
            if not target_path.exists() or hashlib.sha256(target_path.read_bytes()).hexdigest() != source_hash:
                shutil.copy2(source_path, target_path)

        # Handle S3 upload if configured
        if self.backend == "s3" and self.s3_bucket:
            s3_key = f"{job_slug}/{vendor_slug}/{target_filename}"
            try:
                s3_client = self._get_s3_client()
                content_type = "application/pdf" if ext == ".pdf" else f"image/{ext.lstrip('.')}"
                s3_client.upload_file(
                    str(target_path),
                    self.s3_bucket,
                    s3_key,
                    ExtraArgs={"ContentType": content_type},
                )
                rel_path = f"s3://{self.s3_bucket}/{s3_key}"
                return rel_path, target_path
            except Exception as e:
                logger.error(f"S3 upload failed for {target_path} to {self.s3_bucket}/{s3_key}: {e}")
                rel_path = target_path.as_posix()
                return rel_path, target_path

        # Default local posix path
        rel_path = target_path.as_posix()
        return rel_path, target_path

    def get_file_bytes(self, archive_path: str) -> Optional[bytes]:
        """Retrieves raw file bytes from S3 or local storage."""
        if archive_path.startswith("s3://"):
            parts = archive_path.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            s3 = self._get_s3_client()
            resp = s3.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()

        local_p = Path(archive_path)
        if local_p.exists():
            return local_p.read_bytes()
        return None

    def get_presigned_url(self, archive_path: str, expiration: int = 3600) -> Optional[str]:
        """Generates a presigned download URL for S3 stored documents."""
        if not archive_path.startswith("s3://"):
            return None
        parts = archive_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        s3 = self._get_s3_client()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiration,
        )
