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
        """GET /api/authn/status to seed the CSRF cookie/header.

        DSpace 9.1 does not return a CSRF token on GET requests — the token is
        only issued on the first failed write (403).  This method returns
        whatever it finds; the login() method handles the missing-token case
        by retrying after the first 403.
        """
        r = self._s.get(f"{self.base}/api/authn/status", timeout=_TIMEOUT)
        r.raise_for_status()
        token = (
            r.headers.get("DSPACE-XSRF-TOKEN")
            or self._s.cookies.get("DSPACE-XSRF-TOKEN", "")
            or self._s.cookies.get("DSPACE-XSRF-COOKIE", "")
        )
        self.csrf = token
        return token

    def _refresh_csrf(self, response: requests.Response):
        new = (
            response.headers.get("DSPACE-XSRF-TOKEN")
            or self._s.cookies.get("DSPACE-XSRF-COOKIE", "")
        )
        if new:
            self.csrf = new

    def login(self):
        """Authenticate and store JWT + CSRF token for subsequent writes.

        DSpace 9.1 CSRF dance: the first POST to /api/authn/login returns 403
        and seeds the CSRF token in the response header + cookie.  We catch
        that specific 403, extract the token, and retry once.
        """
        if not config.DSPACE_USERNAME or not config.DSPACE_PASSWORD:
            raise IRConnectionError(
                "DSPACE_USERNAME / DSPACE_PASSWORD not configured in .env"
            )
        self._prime_csrf()
        r = self._s.post(
            f"{self.base}/api/authn/login",
            headers={"X-XSRF-TOKEN": self.csrf} if self.csrf else {},
            data={"user": config.DSPACE_USERNAME, "password": config.DSPACE_PASSWORD},
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(r)

        # DSpace 9.1: first write with no/stale CSRF returns 403 + new token.
        if r.status_code == 403 and self.csrf:
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

        facet: one of dateIssued, author, subject, has_content_in_original_bundle,
        entityType, access_status — the actual configured list on this
        instance (confirmed live 2026-07-19 via GET .../api/discover/facets,
        no dsoType filter). "itemtype" is NOT valid here (400) despite
        appearing in some DSpace docs/examples.
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

    def get_collections(self, size: int = 200) -> list[dict]:
        """List all DSpace collections for the deposit UI dropdown."""
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

    def get_submittable_collections(self) -> list[dict]:
        """Return only collections the logged-in user has submission rights to.

        Reads the eperson's group memberships, extracts collection UUIDs from
        COLLECTION_{uuid}_SUBMIT group names, then resolves names via the
        collections endpoint.  Requires prior login().
        """
        if not self.jwt:
            self.login()
        import re as _re
        try:
            # 1. Get authn/status to find eperson link
            r = self._s.get(
                f"{self.base}/api/authn/status",
                headers=self._write_headers(),
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            ep_href = r.json().get("_links", {}).get("eperson", {}).get("href", "")
            if not ep_href:
                return []

            # 2. Fetch eperson → groups link
            r2 = self._s.get(ep_href, headers=self._write_headers(), timeout=_TIMEOUT)
            r2.raise_for_status()
            groups_href = r2.json().get("_links", {}).get("groups", {}).get("href", "")
            if not groups_href:
                return []

            # 3. Extract collection UUIDs from COLLECTION_{uuid}_SUBMIT group names
            r3 = self._s.get(groups_href, headers=self._write_headers(), timeout=_TIMEOUT)
            r3.raise_for_status()
            groups = r3.json().get("_embedded", {}).get("groups", [])
            submit_uuids = set()
            for g in groups:
                m = _re.match(r"COLLECTION_([0-9a-f\-]{36})_SUBMIT", g.get("name", ""))
                if m:
                    submit_uuids.add(m.group(1))

            if not submit_uuids:
                return []

            # 4. Fetch all collections and filter to submittable ones
            all_cols = self.get_collections(size=300)
            return [c for c in all_cols if c["uuid"] in submit_uuids]
        except Exception as exc:
            logger.warning("get_submittable_collections: %s", exc)
            return []

    def get_live_stats(self) -> dict:
        """Composite live stats tile for the dashboard (§7.3)."""
        total = self.get_total_items()
        by_year = self.get_facet("dateIssued", size=30)
        # "itemtype" isn't a real facet on this instance (confirmed live
        # 2026-07-19: 400 Bad Request — GET .../api/discover/facets returns
        # the actual configured list: author, subject, dateIssued,
        # has_content_in_original_bundle, entityType, access_status).
        # "entityType" IS valid but returns zero values here (this instance
        # doesn't populate DSpace entity types), so by_type silently came
        # back empty either way. "subject" is the one facet that actually
        # gives a meaningful category breakdown (SOCIAL SCIENCES, MEDICINE,
        # NATURAL SCIENCES, ...) on the live server.
        by_type = self.get_facet("subject", size=20)
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
            # DSpace 9 requires Content-Type: application/json even for an empty body.
            r = self._s.post(
                f"{self.base}/api/submission/workspaceitems",
                headers={**headers, "Content-Type": "application/json"},
                params=params,
                data="{}",
                timeout=_TIMEOUT,
            )

        self._refresh_csrf(r)
        if r.status_code == 401:
            # JWT expired mid-batch — re-auth once and retry
            self.login()
            r = self._s.post(
                f"{self.base}/api/submission/workspaceitems",
                headers={**self._write_headers(), "Content-Type": "application/json"},
                params=params,
                data="{}",
                timeout=_TIMEOUT,
            )
            self._refresh_csrf(r)

        r.raise_for_status()
        data = r.json()
        # File uploads return {_embedded: {workspaceitems: [{id: ...}]}}
        # Empty-body creates return a flat {id: ...} object.
        ws_id = data.get("id") or (
            data.get("_embedded", {}).get("workspaceitems", [{}])[0].get("id")
        )
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
        if not r2.ok:
            logger.warning("metadata patch failed for ws %s: %s %s", ws_id, r2.status_code, r2.text[:200])

        # 3. Grant the submission license (required by UNILAG DSpace 9 form) ──
        license_patch = [{"op": "replace", "path": "/sections/license/granted", "value": True}]
        rl = self._s.patch(
            f"{self.base}/api/submission/workspaceitems/{ws_id}",
            headers={**self._write_headers(), "Content-Type": "application/json"},
            json=license_patch,
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(rl)
        if not rl.ok:
            logger.warning("license grant failed for ws %s: %s", ws_id, rl.status_code)

        # 4. Check for blocking validation errors before submitting ───────────
        rv = self._s.get(
            f"{self.base}/api/submission/workspaceitems/{ws_id}",
            headers=self._write_headers(),
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(rv)
        if rv.ok:
            errors = rv.json().get("errors", [])
            if errors:
                # DSpace surfaces every blocking validation problem here
                # (missing/invalid required fields per the TARGET
                # COLLECTION's own input-form config, not just a missing
                # file) — previously only the missing-file case was checked
                # for, so any other validation error (e.g. a collection
                # requiring a field our generic Dublin Core patch doesn't
                # set) fell through to step 5's blind POST, which then 422s
                # with the real reason never looked at or logged (confirmed
                # live 2026-07-19 — a deposit failed with just "422 Client
                # Error", no detail, because raise_for_status() never reads
                # the response body). Treat ANY validation error as
                # blocking and log exactly what DSpace is objecting to, so
                # a rejection is actually diagnosable instead of a bare
                # HTTP status code.
                logger.warning(
                    "Workspace item %s has %d validation error(s), aborting before workflow submit: %s",
                    ws_id, len(errors), errors,
                )
                self._s.delete(
                    f"{self.base}/api/submission/workspaceitems/{ws_id}",
                    headers=self._write_headers(),
                    timeout=_TIMEOUT,
                )
                return {
                    "status": "error",
                    "message": f"Collection metadata validation failed: {errors}",
                }

        # 5. Submit to workflow → archived ────────────────────────────────────
        r3 = self._s.post(
            f"{self.base}/api/workflow/workflowitems",
            headers={**self._write_headers(), "Content-Type": "text/uri-list"},
            data=f"{self.base}/api/submission/workspaceitems/{ws_id}",
            timeout=_TIMEOUT,
        )
        self._refresh_csrf(r3)
        if not r3.ok:
            logger.warning(
                "Workflow submission failed for ws %s: %s %s",
                ws_id, r3.status_code, r3.text[:1500],
            )
        r3.raise_for_status()

        dspace_id = r3.json().get("id") or r3.json().get("uuid", "")
        return {"status": "ok", "dspace_id": str(dspace_id), "message": "Deposited"}


# ── Dublin Core field mapping (§6.4) ─────────────────────────────────────────

def _mv(value: str, place: int = 0) -> dict:
    """Build a DSpace 9 metadata value object (language/authority/confidence required)."""
    return {
        "value": value,
        "language": None,
        "authority": None,
        "confidence": -1,
        "place": place,
    }


def _build_metadata_patch(item) -> list[dict]:
    """Build JSON-Patch ops to set DC fields on a DSpace 9 workspace item.

    DSpace 9 requires full value objects with language/authority/confidence/place.
    Multi-value fields are batched into a single op (repeated ops on the same
    path would overwrite instead of append).
    """
    ops = []

    def _add(dc_path: str, value: str, section: str = "traditionalpageone"):
        if value and value.strip():
            ops.append({
                "op": "add",
                "path": f"/sections/{section}/{dc_path}",
                "value": [_mv(value.strip())],
            })

    _add("dc.title", item.title or "")
    _add("dc.date.issued", item.dc_date_issued or "")
    _add("dc.type", item.dc_type or "")
    _add("dc.language.iso", item.dc_language or "en")
    if item.institution:
        _add("dc.publisher", item.institution)

    # URI: prefer explicit dc.identifier.uri, else build from DOI, else fallback to url.
    # dc.rights and dc.identifier.doi are not in the UNILAG submission form.
    doi = item.doi or ""
    uri = (
        item.dc_identifier_uri
        or (f"https://doi.org/{doi}" if doi else "")
        or item.url
        or ""
    )
    _add("dc.identifier.uri", uri)

    # Authors — all in one op so every author is preserved
    author_names = [
        a.name for a in getattr(item, "authors", []) if getattr(a, "name", "")
    ]
    if author_names:
        ops.append({
            "op": "add",
            "path": "/sections/traditionalpageone/dc.contributor.author",
            "value": [_mv(n, i) for i, n in enumerate(author_names)],
        })

    # Abstract and subjects go in traditionalpagetwo (DSpace 9 default layout)
    if item.abstract and item.abstract.strip():
        ops.append({
            "op": "add",
            "path": "/sections/traditionalpagetwo/dc.description.abstract",
            "value": [_mv(item.abstract.strip())],
        })

    subject_tags = [t.strip() for t in (item.dc_subject or "").split(",") if t.strip()]
    if subject_tags:
        ops.append({
            "op": "add",
            "path": "/sections/traditionalpagetwo/dc.subject",
            "value": [_mv(t, i) for i, t in enumerate(subject_tags)],
        })

    # ARK + DocID as identifiers
    other_ids = [v for v in [item.ark, item.docid] if v]
    if other_ids:
        ops.append({
            "op": "add",
            "path": "/sections/traditionalpageone/dc.identifier.other",
            "value": [_mv(v, i) for i, v in enumerate(other_ids)],
        })

    return ops
