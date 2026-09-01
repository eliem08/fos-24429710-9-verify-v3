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
