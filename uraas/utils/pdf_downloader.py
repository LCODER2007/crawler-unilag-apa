"""
PDF Downloader - Downloads and stores PDFs locally with metadata extraction.
Tries direct URL first, then falls back to Unpaywall open-access copy.
"""

import hashlib
import os
from datetime import datetime
from io import BytesIO
from typing import Dict, Optional

import PyPDF2
import requests

UNPAYWALL_EMAIL = "library@unilag.edu.ng"


class PDFDownloader:
    """Handles PDF downloading, storage, and basic metadata extraction."""

    def __init__(self, storage_path: str = "./storage/pdfs"):
        # Convert to absolute path from project root
        if not os.path.isabs(storage_path):
            # Get project root (3 levels up from this file)
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            storage_path = os.path.normpath(os.path.join(project_root, storage_path))

        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)

    def _fetch_pdf_bytes(self, url: str, timeout: int) -> Optional[bytes]:
        """Attempt to download PDF bytes from a URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; URAAS/1.0; mailto:library@unilag.edu.ng)"
        }
        try:
            resp = requests.get(
                url, headers=headers, timeout=timeout, stream=True, allow_redirects=True
            )
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            content = resp.content
            # Accept if content-type says PDF or file starts with PDF magic bytes
            if "pdf" in content_type.lower() or content[:4] == b"%PDF":
                return content
        except Exception:
            pass
        return None

    def _unpaywall_url(self, doi: str) -> Optional[str]:
        """Look up open-access PDF URL via Unpaywall API."""
        if not doi:
            return None
        # Strip prefix if present
        clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        try:
            resp = requests.get(
                f"https://api.unpaywall.org/v2/{clean_doi}",
                params={"email": UNPAYWALL_EMAIL},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                best = data.get("best_oa_location") or {}
                return best.get("url_for_pdf") or best.get("url")
        except Exception:
            pass
        return None

    def download_pdf(
        self, url: str, item_id: int, doi: str = None, timeout: int = 30
    ) -> Optional[Dict]:
        """
        Download PDF from URL, falling back to Unpaywall if blocked.
        Returns dict with file_path, sha256_hash, file_size, page_count or None.
        """
        pdf_content = None

        # 1. Try the direct URL
        if url:
            pdf_content = self._fetch_pdf_bytes(url, timeout)

        # 2. Fallback: Unpaywall open-access copy
        if pdf_content is None and doi:
            oa_url = self._unpaywall_url(doi)
            if oa_url and oa_url != url:
                pdf_content = self._fetch_pdf_bytes(oa_url, timeout)

        if pdf_content is None:
            return None

        sha256_hash = hashlib.sha256(pdf_content).hexdigest()
        filename = f"{item_id}_{sha256_hash[:8]}.pdf"
        file_path = os.path.join(self.storage_path, filename)

        with open(file_path, "wb") as f:
            f.write(pdf_content)

        return {
            "file_path": file_path,
            "sha256_hash": sha256_hash,
            "file_size": len(pdf_content),
            "page_count": self._get_page_count(pdf_content),
            "downloaded_at": datetime.utcnow(),
        }

    def _get_page_count(self, pdf_content: bytes) -> Optional[int]:
        try:
            return len(PyPDF2.PdfReader(BytesIO(pdf_content)).pages)
        except Exception:
            return None

    def extract_first_page_text(self, file_path: str) -> Optional[str]:
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                if reader.pages:
                    return reader.pages[0].extract_text()
        except Exception:
            pass
        return None


pdf_downloader = PDFDownloader()
