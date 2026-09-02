"""Automated Vendor Portal & HTTP Invoice Fetcher."""

import os
import logging
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .models import PortalSourceConfig

logger = logging.getLogger("invoiceledger.portal_fetcher")


class PortalFetcher:
    """Automates downloading invoices from configured vendor portal endpoints, APIs, or URLs."""

    def __init__(self, configs: Optional[List[PortalSourceConfig]] = None):
        self.configs = configs or []
        self._session = requests.Session()

    def add_portal(self, config: PortalSourceConfig):
        self.configs.append(config)

    def fetch_from_portal(
        self,
        portal_config: PortalSourceConfig,
        target_dir: Optional[Path] = None,
    ) -> List[Tuple[Path, Dict[str, Any]]]:
        """Fetches/downloads invoice files from a vendor portal API, webhook, or download URL."""
        if target_dir is None:
            target_dir = Path("downloaded_invoices")
        target_dir.mkdir(parents=True, exist_ok=True)

        results: List[Tuple[Path, Dict[str, Any]]] = []
        if not portal_config.is_active or not portal_config.url:
            return results

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; InvoiceLedger/0.1.0; +https://invoiceledger.local)",
            "Accept": "application/pdf,application/json,image/*,*/*",
        }
        if portal_config.auth_header:
            headers["Authorization"] = portal_config.auth_header
        elif portal_config.api_key:
            headers["X-API-Key"] = portal_config.api_key

        try:
            resp = self._session.get(portal_config.url, headers=headers, timeout=30)
            resp.raise_for_status()

            # Check if direct PDF/image stream or JSON listing
            content_type = resp.headers.get("Content-Type", "").lower()
            if "pdf" in content_type or "image" in content_type or portal_config.url.lower().endswith(".pdf"):
                filename = f"{portal_config.name.replace(' ', '_').lower()}_invoice.pdf"
                dest = target_dir / filename
                dest.write_bytes(resp.content)
                meta = {"source": "portal", "vendor": portal_config.name, "url": portal_config.url}
                results.append((dest, meta))
            elif "json" in content_type:
                # Expecting array of { "id": ..., "download_url": ..., "filename": ... }
                data = resp.json()
                items = data if isinstance(data, list) else data.get("invoices", [])
                for item in items:
                    dl_url = item.get("download_url") or item.get("url")
                    fn = item.get("filename") or f"{portal_config.name}_{item.get('id', 'inv')}.pdf"
                    if dl_url:
                        dl_resp = self._session.get(dl_url, headers=headers, timeout=30)
                        if dl_resp.status_code == 200:
                            dest = target_dir / fn
                            dest.write_bytes(dl_resp.content)
                            meta = {"source": "portal", "vendor": portal_config.name, "url": dl_url, "metadata": item}
                            results.append((dest, meta))
        except Exception as e:
            logger.warning("Failed to fetch invoices from portal '%s' (%s): %s", portal_config.name, portal_config.url, e)

        return results

    def fetch_all(self, target_dir: Optional[Path] = None) -> List[Tuple[Path, Dict[str, Any]]]:
        all_results = []
        for cfg in self.configs:
            all_results.extend(self.fetch_from_portal(cfg, target_dir))
        return all_results
