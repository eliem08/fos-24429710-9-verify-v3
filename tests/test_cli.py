"""Tests for CLI interface."""

import pytest
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def run_cli(*cli_args):
    cmd = [sys.executable, "-m", "invoiceledger.cli"] + list(cli_args)
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def test_cli_jobs():
    res = run_cli("jobs")
    assert res.returncode == 0
    assert "Job Costing" in res.stdout


def test_cli_rules():
    res = run_cli("rules")
    assert res.returncode == 0
    assert "Vendor Automation Rules" in res.stdout


def test_cli_review():
    res = run_cli("review")
    assert res.returncode == 0
    assert "Human Review Queue" in res.stdout


def test_cli_scan():
    sample_file = REPO_ROOT / "sample_invoices" / "fastenal_inv_501.pdf"
    res = run_cli("scan", str(sample_file))
    assert res.returncode == 0
    assert "FAST-6601" in res.stdout


def test_cli_fetch_emails_rejects_password_flag():
    """Verifies that passing --password to fetch-emails is rejected (flag removed for security)."""
    res = run_cli("fetch-emails", "--host", "imap.test.com", "--username", "user", "--password", "secretpass")
    assert res.returncode != 0
    assert "unrecognized arguments" in res.stderr.lower() or "--password" in res.stderr


def test_cli_fetch_emails_reads_env_password(monkeypatch):
    """Verifies that fetch-emails reads IMAP_PASSWORD from environment instead of CLI flag."""
    import os
    from unittest.mock import patch, MagicMock
    from invoiceledger.cli import cmd_fetch_emails
    import argparse

    mock_intake = MagicMock()
    mock_intake.fetch_and_process_emails.return_value = []

    args = argparse.Namespace(
        host="imap.example.com",
        port=993,
        username="contractor@example.com",
        mailbox="INBOX",
        no_ssl=False,
        auto_commit=True,
    )

    with patch.dict(os.environ, {"IMAP_PASSWORD": "env_secret_password"}):
        cmd_fetch_emails(args, mock_intake)
        assert mock_intake.fetch_and_process_emails.called
        call_kwargs = mock_intake.fetch_and_process_emails.call_args[1]
        cfg = call_kwargs.get("config")
        assert cfg is not None
        assert cfg.password == "env_secret_password"
