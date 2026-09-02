"""Tests for durable S3 / Blob Storage backend in Archiver."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from invoiceledger.archiver import Archiver


def test_archiver_s3_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "contractor-invoices-prod")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    mock_s3 = MagicMock()
    mock_s3.upload_file.return_value = None

    with patch("boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        mock_session_cls.return_value = mock_session

        archiver = Archiver(base_dir=str(tmp_path / "local_cache"))
        source_invoice = tmp_path / "fastenal_inv.pdf"
        source_invoice.write_bytes(b"%PDF-1.4 fastenal receipt")

        rel_path, abs_path = archiver.archive_invoice_file(
            source_path=source_invoice,
            job_name="204 Pine Ridge Commercial",
            vendor_name="Fastenal",
            invoice_date="2026-08-10",
            invoice_number="FAST-6601",
        )

        assert rel_path.startswith("s3://contractor-invoices-prod/")
        assert "204-pine-ridge-commercial" in rel_path
        assert "fastenal" in rel_path
        assert abs_path.exists()
        assert mock_s3.upload_file.called


def test_archiver_presigned_url(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "contractor-invoices-prod")

    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://contractor-invoices-prod.s3.amazonaws.com/test?signed=true"

    with patch("boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        mock_session_cls.return_value = mock_session

        archiver = Archiver()
        url = archiver.get_presigned_url("s3://contractor-invoices-prod/101-main/hd/inv1.pdf")
        assert "signed=true" in url


def test_archiver_local_fallback_when_s3_unset(tmp_path, monkeypatch):
    """When S3_BUCKET is unset, archiver falls back to local disk behavior seamlessly."""
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_S3_BUCKET", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    archiver = Archiver(base_dir=str(tmp_path / "local_archive"))
    source_invoice = tmp_path / "homedepot_inv.pdf"
    source_invoice.write_bytes(b"%PDF-1.4 hd receipt")

    rel_path, abs_path = archiver.archive_invoice_file(
        source_path=source_invoice,
        job_name="101 Main St Remodel",
        vendor_name="The Home Depot",
        invoice_date="2026-08-10",
        invoice_number="HD-101",
    )

    assert not rel_path.startswith("s3://")
    assert abs_path.exists()
    assert abs_path.read_bytes() == b"%PDF-1.4 hd receipt"
    assert "101-main-st-remodel" in rel_path


def test_archiver_s3_r2_credentials(tmp_path, monkeypatch):
    """Verifies that S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET work for S3/R2."""
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://accountid.r2.cloudflarestorage.com")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "r2_access_key_123")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "r2_secret_key_456")
    monkeypatch.setenv("S3_BUCKET", "r2-contractor-invoices")

    mock_s3 = MagicMock()
    mock_s3.upload_file.return_value = None

    with patch("boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        mock_session_cls.return_value = mock_session

        archiver = Archiver(base_dir=str(tmp_path / "cache"))
        source = tmp_path / "r2_inv.pdf"
        source.write_bytes(b"%PDF-1.4 r2 content")

        rel_path, abs_path = archiver.archive_invoice_file(
            source_path=source,
            job_name="310 Elm Creek New Build",
            vendor_name="84 Lumber",
            invoice_date="2026-08-15",
            invoice_number="84L-55",
        )

        assert rel_path.startswith("s3://r2-contractor-invoices/")
        assert mock_s3.upload_file.called
        # Check session was initialized with R2 credentials
        mock_session_cls.assert_called_with(
            aws_access_key_id="r2_access_key_123",
            aws_secret_access_key="r2_secret_key_456",
            region_name="us-east-1",
        )
        mock_session.client.assert_called_with("s3", endpoint_url="https://accountid.r2.cloudflarestorage.com")

