"""DSpace 7.x REST API client for the live UNILAG IR.

Spec reference: UNILAG_IR_Build_Spec.docx §4 & §7
Backend base: https://api-ir.unilag.edu.ng/server

Auth pattern (§4.1): prime CSRF token → POST login → JWT + refreshed CSRF.
Every write sends both headers; CSRF rotates on each response and must be
tracked.  Reads on public objects need no auth.
"""

import logging
import os

import requests

from uraas.config import config

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds for IR requests


class IRConnectionError(Exception):
    pass


class DSpaceClient:
    """Thin session-scoped DSpace 7.x REST client.

    Instantiate once per task; do not share across threads.
    """

    def __init__(self):
        self.base = config.DSPACE_API_URL.rstrip("/")
        self._s = requests.Session()
        self._s.headers.update({
            "User-Agent": "URAAS/1.0 (APA Intelligence Platform; uraas-bot@unilag.edu.ng)",
            "Accept": "application/json",
        })
        self.jwt: str | None = None
        self.csrf: str | None = None

    # ── Authentication ────────────────────────────────────────────────────────

    def _prime_csrf(self) -> str:
        """GET /api/authn/status to seed the CSRF cookie/header."""
        r = self._s.get(f"{self.base}/api/authn/status", timeout=_TIMEOUT)
        r.raise_for_status()
        token = (
            r.headers.get("DSPACE-XSRF-TOKEN")
            or self._s.cookies.get("DSPACE-XSRF-TOKEN", "")
        )
        self.csrf = token
        return token

    def _refresh_csrf(self, response: requests.Response):
        new = response.headers.get("DSPACE-XSRF-TOKEN")
        if new:
            self.csrf = new

    def login(self):
        """Authenticate and store JWT + CSRF token for subsequent writes."""
        if not config.DSPACE_USERNAME or not config.DSPACE_PASSWORD:
            raise IRConnectionError(
                "DSPACE_USERNAME / DSPACE_PASSWORD not configured in .env"
            )
        self._prime_csrf()
        r = self._s.post(
            f"{self.base}/api/authn/login",
            headers={"X-XSRF-TOKEN": self.csrf},
            data={"user": config.DSPACE_USERNAME, "password": config.DSPACE_PASSWORD},
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(r)
        if r.status_code == 401:
            raise IRConnectionError("DSpace login failed — check DSPACE_USERNAME/PASSWORD")
        r.raise_for_status()
        auth = r.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            self.jwt = auth[7:]
        else:
            raise IRConnectionError("DSpace login did not return a JWT")

    def _write_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.jwt}",
            "X-XSRF-TOKEN": self.csrf,
        }

    # ── Read-only probes (no auth required) ───────────────────────────────────

    def probe(self) -> dict:
        """Check connectivity and return DSpace version.  Safe to call without creds."""
        try:
            r = self._s.get(f"{self.base}/api", timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return {"ok": True, "version": data.get("dspaceVersion", "unknown")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_total_items(self) -> int:
        """Total archived items via discovery endpoint (§7.2)."""
        try:
            r = self._s.get(
                f"{self.base}/api/discover/search/objects",
                params={"dsoType": "item", "size": 1},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            return (
                r.json()
                .get("_embedded", {})
                .get("searchResult", {})
                .get("page", {})
                .get("totalElements", 0)
            )
        except Exception:
            return 0

    def get_facet(self, facet: str, size: int = 20) -> list[dict]:
        """Return facet buckets from the discovery layer (§7.2).

        facet: one of dateIssued, author, subject, itemtype …
        Returns list of {"label": str, "count": int}.
        """
        try:
            r = self._s.get(
                f"{self.base}/api/discover/facets/{facet}",
                params={"dsoType": "item", "size": size},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            raw = (
                r.json()
                .get("_embedded", {})
                .get("values", [])
            )
            return [{"label": v.get("label", ""), "count": v.get("count", 0)} for v in raw]
        except Exception as exc:
            logger.warning("get_facet %s: %s", facet, exc)
            return []

    def get_collections(self, size: int = 100) -> list[dict]:
        """List all DSpace collections (§4.2) for the deposit UI dropdown."""
        try:
            r = self._s.get(
                f"{self.base}/api/core/collections",
                params={"size": size},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            raw = r.json().get("_embedded", {}).get("collections", [])
            return [
                {"uuid": c.get("uuid", ""), "name": c.get("name", "Unnamed")}
                for c in raw
            ]
        except Exception as exc:
            logger.warning("get_collections: %s", exc)
            return []

    def get_live_stats(self) -> dict:
        """Composite live stats tile for the dashboard (§7.3)."""
        total = self.get_total_items()
        by_year = self.get_facet("dateIssued", size=30)
        by_type = self.get_facet("itemtype", size=20)
        return {
            "total_items": total,
            "by_year": by_year,
            "by_type": by_type,
        }

    # ── Deposit (Path B — REST submission flow, §6.2) ─────────────────────────

    def _check_duplicate(self, doi: str | None, title: str, year: str | None) -> bool:
        """Return True if an item with this DOI or (title+year) already exists in IR."""
        if doi:
            r = self._s.get(
                f"{self.base}/api/discover/search/objects",
                params={"query": f"dc.identifier.uri:{doi}", "dsoType": "item", "size": 1},
                timeout=_TIMEOUT,
            )
            try:
                if r.json().get("_embedded", {}).get("searchResult", {}).get("page", {}).get("totalElements", 0) > 0:
                    return True
            except Exception:
                pass
        # Normalised title check
        safe_title = title.replace('"', '\\"')[:100]
        r = self._s.get(
            f"{self.base}/api/discover/search/objects",
            params={"query": f'dc.title:"{safe_title}"', "dsoType": "item", "size": 1},
            timeout=_TIMEOUT,
        )
        try:
            return (
                r.json()
                .get("_embedded", {})
                .get("searchResult", {})
                .get("page", {})
                .get("totalElements", 0)
            ) > 0
        except Exception:
            return False

    def deposit_item(
        self,
        collection_uuid: str,
        item,  # uraas.database.Item ORM object
        pdf_path: str | None = None,
    ) -> dict:
        """
        Deposit one item to the IR and return a result dict.

        Steps (§6.2):
          1. Create workspace item in the target collection (optionally with PDF)
          2. PATCH Dublin Core metadata
          3. POST to workflow → archived

        Returns {"status": "ok"|"duplicate"|"error", "dspace_id": ..., "message": ...}
        """
        if not self.jwt:
            self.login()

        # Idempotency guard (§8 operational concerns)
        if self._check_duplicate(item.doi, item.title or "", item.dc_date_issued):
            return {"status": "duplicate", "message": "Already exists in IR"}

        # 1. Create workspace item ──────────────────────────────────────────────
        headers = self._write_headers()
        params = {"owningCollection": collection_uuid}

        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as fh:
                r = self._s.post(
                    f"{self.base}/api/submission/workspaceitems",
                    headers=headers,
                    params=params,
                    files={"file": (os.path.basename(pdf_path), fh, "application/pdf")},
                    timeout=60,
                )
        else:
            r = self._s.post(
                f"{self.base}/api/submission/workspaceitems",
                headers=headers,
                params=params,
                timeout=_TIMEOUT,
            )

        self._refresh_csrf(r)
        if r.status_code == 401:
            # JWT expired mid-batch — re-auth once and retry
            self.login()
            r = self._s.post(
                f"{self.base}/api/submission/workspaceitems",
                headers=self._write_headers(),
                params=params,
                timeout=_TIMEOUT,
            )
            self._refresh_csrf(r)

        r.raise_for_status()
        ws_id = r.json().get("id")
        if not ws_id:
            return {"status": "error", "message": "No workspace item ID returned"}

        # 2. PATCH Dublin Core metadata ────────────────────────────────────────
        patch_ops = _build_metadata_patch(item)
        r2 = self._s.patch(
            f"{self.base}/api/submission/workspaceitems/{ws_id}",
            headers={**self._write_headers(), "Content-Type": "application/json"},
            json=patch_ops,
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(r2)
        # A failed patch is non-fatal — the item still ends up in the IR, just with
        # less metadata; log the warning and continue.
        if not r2.ok:
            logger.warning("metadata patch failed for ws %s: %s %s", ws_id, r2.status_code, r2.text[:200])

        # 3. Deposit to workflow ───────────────────────────────────────────────
        r3 = self._s.post(
            f"{self.base}/api/workflow/workflowitems",
            headers={**self._write_headers(), "Content-Type": "text/uri-list"},
            data=f"{self.base}/api/submission/workspaceitems/{ws_id}",
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(r3)
        r3.raise_for_status()

        dspace_id = r3.json().get("id") or r3.json().get("uuid", "")
        return {"status": "ok", "dspace_id": str(dspace_id), "message": "Deposited"}


# ── Dublin Core field mapping (§6.4) ─────────────────────────────────────────

def _build_metadata_patch(item) -> list[dict]:
    """Build JSON-Patch ops to set DC fields on a DSpace workspace item."""
    ops = []

    def _add(dc_path: str, value: str):
        if value and value.strip():
            ops.append({
                "op": "add",
                "path": f"/sections/traditionalpageone/{dc_path}",
                "value": [{"value": value.strip()}],
            })

    _add("dc.title", item.title or "")
    _add("dc.description.abstract", item.abstract or "")
    _add("dc.date.issued", item.dc_date_issued or "")
    _add("dc.rights", item.dc_rights or "")
    _add("dc.type", item.dc_type or "")
    _add("dc.language.iso", item.dc_language or "en")
    _add("dc.identifier.uri", item.dc_identifier_uri or item.url or "")
    _add("dc.identifier.doi", item.doi or "")
    if item.institution:
        _add("dc.publisher", item.institution)

    # Authors — one patch op per author
    for author in getattr(item, "authors", []):
        name = getattr(author, "name", "")
        if name:
            ops.append({
                "op": "add",
                "path": "/sections/traditionalpageone/dc.contributor.author",
                "value": [{"value": name}],
            })

    # Subject tags
    for tag in (item.dc_subject or "").split(","):
        tag = tag.strip()
        if tag:
            ops.append({
                "op": "add",
                "path": "/sections/traditionalpageone/dc.subject",
                "value": [{"value": tag}],
            })

    # ARK / DocID as identifiers
    if item.ark:
        _add("dc.identifier.other", item.ark)
    if item.docid:
        _add("dc.identifier.other", item.docid)

    return ops
