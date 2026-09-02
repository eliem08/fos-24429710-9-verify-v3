"""Tests for extended CLI commands (vendors, spreadsheet, export)."""

import pytest
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def run_cli(*cli_args):
    cmd = [sys.executable, "-m", "invoiceledger.cli"] + list(cli_args)
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def test_cli_vendors():
    res = run_cli("vendors")
    assert res.returncode == 0
    assert "Registered Vendor Directory" in res.stdout
    assert "The Home Depot" in res.stdout


def test_cli_vendors_add():
    res = run_cli("vendors", "--add-name", "Pioneer Roofing Supply", "--aliases", "Pioneer Roofing,Pioneer")
    assert res.returncode == 0
    assert "Added custom vendor" in res.stdout


def test_cli_spreadsheet_sync(tmp_path):
    out_xlsx = str(tmp_path / "101_Main_Test_PL.xlsx")
    res = run_cli("spreadsheet", "--job", "101 Main St Remodel", "-o", out_xlsx)
    assert res.returncode == 0
    assert "Successfully updated Job P&L" in res.stdout
    assert Path(out_xlsx).exists()


def test_cli_export_xlsx(tmp_path):
    out_xlsx = str(tmp_path / "Export_All.xlsx")
    res = run_cli("export", "--format", "xlsx", "-o", out_xlsx)
    assert res.returncode == 0
    assert "Exported" in res.stdout
    assert Path(out_xlsx).exists()
