"""Tests for automated EmailFetcher (IMAP/POP3 attachment downloading)."""

import email
import email.message
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from invoiceledger.email_fetcher import EmailFetcher, decode_str
from invoiceledger.models import EmailSourceConfig


def test_decode_str():
    assert decode_str("Simple Subject") == "Simple Subject"
    assert decode_str("=?utf-8?B?SW52b2ljZSAjMTIzNDU=?=") == "Invoice #12345"


def test_email_fetcher_imap_download(tmp_path):
    config = EmailSourceConfig(
        id="test-imap",
        host="imap.example.com",
        port=993,
        username="contractor@example.com",
        password="secretpassword",
        mailbox="INBOX",
        use_ssl=True,
    )

    fetcher = EmailFetcher(config)
    target_dir = tmp_path / "downloads"

    # Build mock email with invoice attachment
    msg = email.message.EmailMessage()
    msg["Subject"] = "Invoice from ABC Supply"
    msg["From"] = "billing@abcsupply.com"
    msg["Date"] = "Mon, 10 Aug 2026 10:00:00 -0400"
    msg.set_content("Please find attached your invoice.")
    sample_pdf_bytes = b"%PDF-1.4 mock invoice bytes"
    msg.add_attachment(sample_pdf_bytes, maintype="application", subtype="pdf", filename="ABC_55102.pdf")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"1 2"])
    mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100}", msg.as_bytes()), b")"])
    mock_imap.store.return_value = ("OK", [b"Flags updated"])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        results = fetcher.fetch_attachments(target_dir=target_dir)

        assert len(results) >= 1
        file_path, meta = results[0]
        assert file_path.exists()
        assert file_path.read_bytes() == sample_pdf_bytes
        assert meta["source"] == "email"
        assert "ABC Supply" in meta["subject"]
        assert mock_imap.store.called


def test_email_fetcher_pop3_download(tmp_path):
    config = EmailSourceConfig(
        id="test-pop3",
        host="pop.example.com",
        port=995,
        username="contractor@example.com",
        password="secretpassword",
        protocol="pop3",
        use_ssl=True,
    )

    fetcher = EmailFetcher(config)
    target_dir = tmp_path / "pop_downloads"

    msg = email.message.EmailMessage()
    msg["Subject"] = "Ferguson Invoice 10940"
    msg["From"] = "invoicing@ferguson.com"
    msg.set_content("Attached is your invoice.")
    pdf_bytes = b"%PDF-1.4 ferguson invoice bytes"
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="FERG_10940.pdf")

    mock_pop = MagicMock()
    mock_pop.user.return_value = b"+OK"
    mock_pop.pass_.return_value = b"+OK"
    mock_pop.list.return_value = (b"+OK", [b"1 500"])
    lines = msg.as_bytes().split(b"\r\n")
    mock_pop.retr.return_value = (b"+OK", lines, 500)

    with patch("poplib.POP3_SSL", return_value=mock_pop):
        results = fetcher.fetch_attachments(target_dir=target_dir)
        assert len(results) >= 1
        file_path, meta = results[0]
        assert file_path.exists()
        assert file_path.read_bytes() == pdf_bytes
        assert "Ferguson" in meta["subject"]


def test_fetch_and_process_messages_seen_after_success(tmp_path):
    """Verifies that \\Seen flag is stored ONLY after the processing callback succeeds."""
    config = EmailSourceConfig(
        id="test-imap-atomic",
        host="imap.example.com",
        port=993,
        username="contractor@example.com",
        password="secretpassword",
        mailbox="INBOX",
        use_ssl=True,
    )

    fetcher = EmailFetcher(config)
    target_dir = tmp_path / "atomic_downloads"

    msg = email.message.EmailMessage()
    msg["Subject"] = "Invoice from 84 Lumber"
    msg["From"] = "invoices@84lumber.com"
    msg.set_content("Please find attached.")
    pdf_bytes = b"%PDF-1.4 84 lumber invoice"
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="84L_1234.pdf")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"42"])
    mock_imap.fetch.return_value = ("OK", [(b"42 (RFC822 {100}", msg.as_bytes()), b")"])
    mock_imap.store.return_value = ("OK", [b"Flags updated"])

    processed_files = []

    def mock_process(file_path: Path):
        processed_files.append(file_path)
        return {"file": file_path.name, "status": "processed"}

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        results = fetcher.fetch_and_process_messages(mock_process, target_dir=target_dir)
        assert len(results) == 1
        assert len(processed_files) == 1
        # Assert \\Seen was stored after processing
        mock_imap.store.assert_called_once_with(b"42", "+FLAGS", "\\Seen")


def test_fetch_and_process_messages_not_seen_on_crash(tmp_path):
    """If process_callback raises an error during processing, the message must NOT be marked \\Seen."""
    config = EmailSourceConfig(
        id="test-imap-crash",
        host="imap.example.com",
        port=993,
        username="contractor@example.com",
        password="secretpassword",
        mailbox="INBOX",
        use_ssl=True,
    )

    fetcher = EmailFetcher(config)
    target_dir = tmp_path / "crash_downloads"

    msg = email.message.EmailMessage()
    msg["Subject"] = "Corrupted Invoice"
    msg["From"] = "bad@vendor.com"
    msg.set_content("Attached invoice.")
    msg.add_attachment(b"bad bytes", maintype="application", subtype="pdf", filename="bad.pdf")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"99"])
    mock_imap.fetch.return_value = ("OK", [(b"99 (RFC822 {100}", msg.as_bytes()), b")"])

    def crash_process(file_path: Path):
        raise RuntimeError("Crash during extraction!")

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        with pytest.raises(RuntimeError):
            fetcher.fetch_and_process_messages(crash_process, target_dir=target_dir)

        # Assert \\Seen was NEVER called because callback crashed
        assert not mock_imap.store.called


def test_email_fetcher_missing_credentials_logged(tmp_path, caplog):
    """When credentials are not configured, EmailFetcher logs a warning and returns empty."""
    import logging
    config = EmailSourceConfig(
        id="empty-cfg",
        host="",
        username="",
        password="",
    )
    fetcher = EmailFetcher(config)
    with caplog.at_level(logging.WARNING):
        res = fetcher.fetch_and_process_messages(lambda p: None, target_dir=tmp_path)
        assert res == []
        assert "credentials" in caplog.text.lower()

