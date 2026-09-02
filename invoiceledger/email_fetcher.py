"""Automated Email Ingestion & Attachment Downloader supporting IMAP and POP3."""

import os
import email
import logging
import imaplib
import poplib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from email.header import decode_header

from .models import EmailSourceConfig

logger = logging.getLogger("invoiceledger.email_fetcher")


def decode_str(header_val: Any) -> str:
    """Decodes MIME encoded header strings."""
    if not header_val:
        return ""
    decoded_fragments = decode_header(header_val)
    parts = []
    for content, encoding in decoded_fragments:
        if isinstance(content, bytes):
            try:
                parts.append(content.decode(encoding or "utf-8", errors="replace"))
            except Exception:
                parts.append(content.decode("latin-1", errors="replace"))
        else:
            parts.append(str(content))
    return " ".join(parts).strip()


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


class EmailFetcher:
    """Automates downloading invoice attachments from vendor emails via IMAP/POP3."""

    def __init__(self, config: Optional[EmailSourceConfig] = None):
        self.config = config or self._load_config_from_env()

        if _is_cloud_environment() and not (os.environ.get("S3_BUCKET") or os.environ.get("AWS_S3_BUCKET")):
            logger.warning(
                "CRITICAL PERSISTENCE WARNING: Email attachment downloader is configured with local ephemeral storage ('downloaded_invoices/') on a cloud host. "
                "Downloaded attachments will not survive a restart/redeploy. "
                "Configure durable S3 storage (S3_BUCKET / AWS_S3_BUCKET) to ensure persistence."
            )

    @staticmethod
    def _load_config_from_env() -> EmailSourceConfig:
        return EmailSourceConfig(
            id="env_config",
            host=os.environ.get("IMAP_HOST", os.environ.get("IMAP_SERVER", "")),
            port=int(os.environ.get("IMAP_PORT", "993")),
            username=os.environ.get("IMAP_USERNAME", os.environ.get("IMAP_USER", "")),
            password=os.environ.get("IMAP_PASSWORD", ""),
            mailbox=os.environ.get("IMAP_MAILBOX", "INBOX"),
            use_ssl=os.environ.get("IMAP_USE_SSL", "true").lower() in ("true", "1", "yes"),
            protocol=os.environ.get("EMAIL_PROTOCOL", "imap").lower(),
            search_criteria=os.environ.get("IMAP_SEARCH", "UNSEEN"),
            mark_as_read=os.environ.get("IMAP_MARK_SEEN", "true").lower() in ("true", "1", "yes"),
        )

    def fetch_attachments(
        self,
        target_dir: Optional[Path] = None,
        search_criteria: Optional[str] = None,
    ) -> List[Tuple[Path, Dict[str, Any]]]:
        """Connects to mailbox, searches matching messages, downloads invoice attachments.
        Returns list of (file_path, email_metadata).
        """
        if target_dir is None:
            target_dir = Path("downloaded_invoices")
        target_dir.mkdir(parents=True, exist_ok=True)

        if not self.config.username or not self.config.password or not self.config.host:
            logger.warning("EmailFetcher.fetch_attachments: IMAP/POP3 credentials (host, username, password) are missing. Skipping fetch.")
            return []

        if self.config.protocol == "pop3":
            return self._fetch_pop3(target_dir)
        return self._fetch_imap(target_dir, search_criteria or self.config.search_criteria)

    def fetch_and_process_messages(
        self,
        process_callback,
        target_dir: Optional[Path] = None,
        search_criteria: Optional[str] = None,
    ) -> List[Any]:
        """Connects to IMAP mailbox, retrieves unseen messages with attachments,
        runs each attachment through process_callback, and ONLY marks the message
        \\Seen after all its attachments are fully processed.
        """
        if target_dir is None:
            target_dir = Path("downloaded_invoices")
        target_dir.mkdir(parents=True, exist_ok=True)

        if not self.config.username or not self.config.password or not self.config.host:
            logger.warning("EmailFetcher.fetch_and_process_messages: IMAP credentials (host, username, password) are missing in configuration. No messages will be polled.")
            return []

        search_criteria = search_criteria or self.config.search_criteria or "UNSEEN"
        imap_cls = imaplib.IMAP4_SSL if self.config.use_ssl else imaplib.IMAP4
        client = imap_cls(self.config.host, self.config.port)
        results = []
        try:
            client.login(self.config.username, self.config.password)
            client.select(self.config.mailbox)

            status, msg_ids = client.search(None, search_criteria)
            if status != "OK" or not msg_ids or not msg_ids[0]:
                return results

            id_list = msg_ids[0].split()
            for msg_id in id_list:
                status, data = client.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                msg_attachments: List[Path] = []
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None and not part.get_filename():
                        continue

                    raw_fn = part.get_filename()
                    fn = decode_str(raw_fn) if raw_fn else None
                    if fn and any(fn.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".txt"]):
                        payload = part.get_payload(decode=True)
                        if payload:
                            clean_name = "".join(c for c in fn if c.isalnum() or c in "._- ")
                            if not clean_name:
                                clean_name = f"invoice_{msg_id.decode() if isinstance(msg_id, bytes) else msg_id}.pdf"
                            file_path = target_dir / clean_name
                            counter = 1
                            while file_path.exists():
                                file_path = target_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                                counter += 1

                            file_path.write_bytes(payload)
                            msg_attachments.append(file_path)

                if msg_attachments:
                    # Run all attachments for this message through the pipeline
                    for att in msg_attachments:
                        processed = process_callback(att)
                        if processed is not None:
                            results.append(processed)

                    # Only mark message \Seen after full successful processing
                    if self.config.mark_as_read:
                        client.store(msg_id, "+FLAGS", "\\Seen")
                else:
                    # No attachments in message
                    if self.config.mark_as_read:
                        client.store(msg_id, "+FLAGS", "\\Seen")

        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

        return results

    def _fetch_imap(
        self,
        target_dir: Path,
        search_criteria: str,
    ) -> List[Tuple[Path, Dict[str, Any]]]:
        results: List[Tuple[Path, Dict[str, Any]]] = []
        if not self.config.username or not self.config.password:
            return results

        imap_cls = imaplib.IMAP4_SSL if self.config.use_ssl else imaplib.IMAP4
        client = imap_cls(self.config.host, self.config.port)
        try:
            client.login(self.config.username, self.config.password)
            client.select(self.config.mailbox)

            status, msg_ids = client.search(None, search_criteria)
            if status != "OK" or not msg_ids or not msg_ids[0]:
                return results

            id_list = msg_ids[0].split()
            for msg_id in id_list:
                status, data = client.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                sender = decode_str(msg.get("From", ""))
                subject = decode_str(msg.get("Subject", ""))
                date_str = decode_str(msg.get("Date", ""))

                meta = {
                    "source": "email",
                    "sender": sender,
                    "subject": subject,
                    "date": date_str,
                    "msg_id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                }

                found_attachments = False
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None and not part.get_filename():
                        continue

                    raw_fn = part.get_filename()
                    fn = decode_str(raw_fn) if raw_fn else None
                    if fn and any(fn.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff"]):
                        payload = part.get_payload(decode=True)
                        if payload:
                            clean_name = "".join(c for c in fn if c.isalnum() or c in "._- ")
                            if not clean_name:
                                clean_name = f"invoice_{msg_id}.pdf"
                            file_path = target_dir / clean_name
                            counter = 1
                            while file_path.exists():
                                file_path = target_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                                counter += 1

                            file_path.write_bytes(payload)
                            results.append((file_path, meta))
                            found_attachments = True

                if self.config.mark_as_read and found_attachments:
                    client.store(msg_id, "+FLAGS", "\\Seen")

        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

        return results

    def _fetch_pop3(self, target_dir: Path) -> List[Tuple[Path, Dict[str, Any]]]:
        results: List[Tuple[Path, Dict[str, Any]]] = []
        if not self.config.username or not self.config.password:
            return results

        pop_cls = poplib.POP3_SSL if self.config.use_ssl else poplib.POP3
        client = pop_cls(self.config.host, self.config.port)
        try:
            client.user(self.config.username)
            client.pass_(self.config.password)
            num_messages = len(client.list()[1])

            for i in range(1, num_messages + 1):
                raw_lines = client.retr(i)[1]
                raw_bytes = b"\r\n".join(raw_lines)
                msg = email.message_from_bytes(raw_bytes)
                sender = decode_str(msg.get("From", ""))
                subject = decode_str(msg.get("Subject", ""))
                meta = {"source": "email_pop3", "sender": sender, "subject": subject}

                for part in msg.walk():
                    fn = decode_str(part.get_filename() or "")
                    if fn and any(fn.lower().endswith(ext) for ext in [".pdf", ".png", ".jpg", ".jpeg"]):
                        payload = part.get_payload(decode=True)
                        if payload:
                            file_path = target_dir / fn
                            file_path.write_bytes(payload)
                            results.append((file_path, meta))
        finally:
            try:
                client.quit()
            except Exception:
                pass

        return results
