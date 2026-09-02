"""Tests for database persistence configuration (DATABASE_URL, SQLite fallback, Postgres connection)."""

import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from invoiceledger.storage import Storage
from invoiceledger.models import Job, VendorRule, ColumnMappingTemplate


def test_storage_fallback_sqlite_when_database_url_unset(tmp_path, monkeypatch):
    """When DATABASE_URL is unset, Storage should default to local SQLite file."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    test_db = tmp_path / "fallback_test.db"
    
    storage = Storage(str(test_db))
    assert not storage.is_postgres
    assert storage.db_target == str(test_db)

    # Verify SQLite file exists and schema was created
    assert test_db.exists()
    jobs = storage.list_jobs()
    assert len(jobs) >= 3


def test_storage_accepts_postgres_url(monkeypatch):
    """When DATABASE_URL is a postgres:// URL, Storage connects via psycopg."""
    pg_url = "postgres://contractor_user:securepass@db.render.internal:5432/invoiceledger_prod"
    monkeypatch.setenv("DATABASE_URL", pg_url)

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor

    with patch("psycopg.connect", return_value=mock_conn) as mock_connect:
        storage = Storage()
        assert storage.is_postgres
        assert storage.db_target == pg_url
        assert mock_connect.called

        # Verify SQL formatting replaces ? with %s for Postgres
        sql_with_params = storage._format_sql("SELECT * FROM invoices WHERE id = ? AND status = ?")
        assert sql_with_params == "SELECT * FROM invoices WHERE id = %s AND status = %s"


def test_storage_accepts_postgresql_url(monkeypatch):
    """When DATABASE_URL is a postgresql:// URL, Storage connects via psycopg."""
    pg_url = "postgresql://user:pass@host:5432/dbname"
    monkeypatch.setenv("DATABASE_URL", pg_url)

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor

    with patch("psycopg.connect", return_value=mock_conn) as mock_connect:
        storage = Storage()
        assert storage.is_postgres
        assert storage.db_target == pg_url
        assert mock_connect.called


def test_storage_cloud_fail_fast_when_enforced(tmp_path, monkeypatch):
    """When running on cloud PaaS and FAIL_ON_EPHEMERAL_STORAGE is enabled, Storage fails fast if DATABASE_URL is unset."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("FAIL_ON_EPHEMERAL_STORAGE", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        Storage(str(tmp_path / "ephemeral.db"))

    assert "DATABASE" in str(exc_info.value)

