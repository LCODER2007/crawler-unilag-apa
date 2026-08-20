"""Africa PID Alliance DOCiD(TM) registration client — the REAL platform API,
distinct from uraas.utils.docid_generator (a purely local placeholder that
fabricates a plausible-looking "20.500.14351/[hash]" identifier and a
"https://docid.africapidalliance.org/resolve/..." URL that was never actually
registered with the real service).

Schema below is reverse-engineered from the platform's own public frontend
source (github.com/Africa-PID-Alliance/DOCiD, actively deployed, checked
2026-07-19) plus live read-only (GET) requests against the production API —
NOT from docid.africapidalliance.org/docs/*, which describes a materially
different (older/aspirational) shape: that page documents `/api/v1/...`
endpoints returning JSON bodies for `/publications/publish`, but the actual
deployed frontend (frontend/src/app/api/publications/publish/route.js in the
repo) posts multipart/form-data to a same-origin proxy at plain `/api/...`
(no /v1) which forwards to the real Flask backend server-side — the backend's
own address is a private env var never shipped to the browser, but the public
proxy at docid.africapidalliance.org/api/* works fine as a base URL and is
what this client targets.

Confirmed live and working (read-only, 2026-07-19):
  GET  /api/publications/get-list-resource-types      -> [{id, resource_type}]
  GET  /api/publications/get-list-publication-types    -> [{id, publication_type_name}]
  GET  /api/publications/get-list-creators-roles       -> [{role_id, role_name}]
  GET  /api/publications/get-publications              -> {data:[...], pagination:...}
  POST /api/auth/login {email,password}                -> 401 body {"message":..., "status":false}
                                                            on bad creds (success shape unconfirmed —
                                                            no valid credentials to test with yet)
  POST /api/cordoi/assign-doi/container-id {title,description} (no auth required!) ->
       {"data":{"id": "20.500.14351/...", "attributes":{...}}, "id": "...",
        "type":"Container iD", "message":"Object created successfully", "success":true}
       *** This call actually WRITES a real record on the live production
       system — do not call it outside of a genuine registration flow. It was
       called once during development for schema discovery and left a
       harmless test object (20.500.14351/d823920b601a74c29754) on the real
       platform; be deliberate about calling it again. ***

Real DOCiDs are assigned via that /cordoi/assign-doi/container-id call (NOT
generated locally) and then included as `documentDocid` in the /publish
FormData — the backend just stores whatever id string was assigned in step 1.

/publications/publish itself (POST, multipart/form-data, Authorization:
Bearer <token> required) was read from source but never called live (it's
the actual "create a real, permanent, publicly-visible publication record"
action — that needs real credentials and explicit intent, not schema
discovery). Field names below come directly from
frontend/src/app/assign-docid/page.jsx's `submitData.append(...)` calls.
"""

import json
import logging
import uuid

import requests

from uraas.config import config
from uraas.utils.ai_classifier import sanitize_text

logger = logging.getLogger(__name__)

_TIMEOUT = 20
DEFAULT_BASE_URL = "https://docid.africapidalliance.org/api"


class DocIDConnectionError(Exception):
    pass


class DocIDClient:
    """Thin session-scoped client for the real DOCiD registration API.

    Instantiate once per task; do not share across threads. Requires
    DOCID_EMAIL/DOCID_PASSWORD configured (raises DocIDConnectionError
    otherwise) as a blanket safety gate — several read endpoints below don't
    actually need auth, but this client refuses to do anything, including
    the no-auth-required container-id assignment (which WRITES to the real
    platform), until real credentials are configured, so a bare
    `DocIDClient()` can never fire off an unintended live registration.
    """

    def __init__(self):
        if not (config.DOCID_EMAIL and config.DOCID_PASSWORD):
            raise DocIDConnectionError(
                "DOCID_EMAIL / DOCID_PASSWORD not configured in .env — DOCiD "
                "registration is disabled until you have a real account "
                "(the API base URL itself is now known and defaulted, no "
                "longer something you need to supply)."
            )
        self.base = config.DOCID_API_URL or DEFAULT_BASE_URL
        self._s = requests.Session()
        self._s.headers.update({
            "User-Agent": "URAAS/1.0 (APA Intelligence Platform; uraas-bot@unilag.edu.ng)",
            "Accept": "application/json",
        })
        self.access_token: str | None = None
        self.user_id: int | None = None
        self._ref_cache: dict = {}

    def login(self):
        r = self._s.post(
            f"{self.base}/auth/login",
            json={"email": config.DOCID_EMAIL, "password": config.DOCID_PASSWORD},
            timeout=_TIMEOUT,
        )
        if r.status_code == 401:
            raise DocIDConnectionError("DOCiD login failed — check DOCID_EMAIL/PASSWORD")
        r.raise_for_status()
        data = r.json()
        # Response shape for a SUCCESSFUL login was never confirmed live (only
        # the 401 failure body, {"message":..., "status":false}, was seen) —
        # try several plausible nestings defensively rather than assume one.
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        token = (
            inner.get("access_token")
            or inner.get("token")
            or inner.get("accessToken")
        )
        if not token:
            raise DocIDConnectionError(
                f"DOCiD login did not return a recognizable token — response: {data!r}"
            )
        self.access_token = token
        self._s.headers["Authorization"] = f"Bearer {token}"
        user = inner.get("user") if isinstance(inner.get("user"), dict) else inner
        self.user_id = user.get("id") or user.get("user_id")

    def _get(self, path: str, auth: bool = False) -> dict | list:
        if auth and not self.access_token:
            self.login()
        r = self._s.get(f"{self.base}{path}", timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    # ── Reference data (cached, public — confirmed working without auth) ────

    def get_resource_types(self) -> list[dict]:
        if "resource_types" not in self._ref_cache:
            self._ref_cache["resource_types"] = self._get(
                "/publications/get-list-resource-types"
            )
        return self._ref_cache["resource_types"]

    def get_publication_types(self) -> list[dict]:
        if "publication_types" not in self._ref_cache:
            self._ref_cache["publication_types"] = self._get(
                "/publications/get-list-publication-types"
            )
        return self._ref_cache["publication_types"]

    def get_creator_roles(self) -> list[dict]:
        if "creator_roles" not in self._ref_cache:
            self._ref_cache["creator_roles"] = self._get(
                "/publications/get-list-creators-roles"
            )
        return self._ref_cache["creator_roles"]

    def _resolve_resource_type_id(self, want_name: str) -> int:
        want = (want_name or "").strip().lower()
        for row in self.get_resource_types():
            if str(row.get("resource_type", "")).strip().lower() == want:
                return row["id"]
        # "Manuscripts" (id 7 as of 2026-07-19) is the closest generic fit for
        # a journal-article-shaped item among the confirmed real categories
        # (Indigeneous Knowledge [sic], Patent, Cultural Heritage, Project,
        # Funder, DMP, Manuscripts) — none of which is a plain "Article".
        for row in self.get_resource_types():
            if "manuscript" in str(row.get("resource_type", "")).lower():
                return row["id"]
        return self.get_resource_types()[0]["id"]

    def _resolve_publication_type_id(self, want_name: str) -> int:
        want = (want_name or "").strip().lower()
        for row in self.get_publication_types():
            if str(row.get("publication_type_name", "")).strip().lower() == want:
                return row["id"]
        for row in self.get_publication_types():
            if row.get("publication_type_name") == "Article":
                return row["id"]
        return self.get_publication_types()[0]["id"]

    def _resolve_creator_role_id(self, want_name: str = "Author") -> str:
        want = (want_name or "Author").strip().lower()
        for row in self.get_creator_roles():
            if str(row.get("role_name", "")).strip().lower() == want:
                return row["role_id"]
        for row in self.get_creator_roles():
            if row.get("role_name") == "Author":
                return row["role_id"]
        return self.get_creator_roles()[0]["role_id"]

    # ── Real DOCiD assignment ─────────────────────────────────────────────

    def assign_docid(self, title: str, description: str) -> str:
        """Register a new container/DOCiD for one publication and return the
        assigned id string (e.g. "20.500.14351/..."). This WRITES a real,
        permanent-looking record on the live platform the moment it's
        called, even though the endpoint itself needs no auth — only call
        it as part of an actual publish flow, never for exploration."""
        if not self.access_token:
            self.login()
        # As of 2026-07-28 the endpoint rejects requests with 400 "A valid
        # Idempotency-Key header (8-128 characters) is required" — added on
        # their end since the original schema discovery (not documented
        # anywhere public). A fresh UUID per call is correct here: this is a
        # genuinely new registration each time, not a retry of a prior one.
        # Live-verified 2026-07-28: this endpoint is slow enough to exceed
        # the default 20s timeout under normal conditions (not an outage) —
        # give it real headroom rather than treating a slow-but-healthy
        # response as a failure.
        r = self._s.post(
            f"{self.base}/cordoi/assign-doi/container-id",
            json={"title": title, "description": description},
            headers={"Idempotency-Key": str(uuid.uuid4())},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        docid = (data.get("data") or {}).get("id") or data.get("id")
        if not docid:
            raise DocIDConnectionError(f"assign-doi did not return an id — response: {data!r}")
        return docid

    # ── Publish ────────────────────────────────────────────────────────────

    def publish_item(self, item) -> dict:
        """Register one uraas.database.Item with the real DOCiD platform:
        assigns a real docid, then submits the full publication record.
        Returns the raw /publish response. Callers should persist the
        assigned docid (from assign_docid, already set on the record before
        /publish is even called) onto Item.docid / Item.docid_assigned_at.

        NOT yet exercised end-to-end against the live server (that requires
        a real account + deliberately creating a real, permanent, publicly-
        visible record) — the request shape is transcribed directly from the
        platform's own source (assign-docid/page.jsx), not guessed, but
        treat the very first real call as a validation run.
        """
        if not self.access_token:
            self.login()
        if not self.user_id:
            raise DocIDConnectionError(
                "No user_id available from login — cannot attribute this publication to an account"
            )

        # Belt-and-suspenders: the ingest pipeline (uraas/pipelines/database.py)
        # already sanitizes title/abstract on the way in, but rows written
        # before that fix existed (or via any future path that bypasses it)
        # can still carry raw JATS/HTML markup ("<jats:p>...") — confirmed
        # live 2026-07-28 when an unsanitized Crossref abstract was sent
        # straight through to a real published record. Never send raw text
        # to this permanent, public, third-party registry.
        title = sanitize_text(item.title) or item.title or ""
        description = sanitize_text(item.abstract) or item.abstract or ""
        docid = self.assign_docid(title, description)

        # The real resource-type catalog (confirmed live 2026-07-28) has
        # dedicated categories for two of our own SC categories —
        # "Indigeneous Knowledge" [sic] and "Cultural Heritage" — use those
        # when the item was actually classified into them instead of the
        # generic "Manuscripts" fallback; every other SC category (African
        # Literature, Postcolonial Studies, etc.) has no dedicated bucket on
        # their end and is genuinely journal-article-shaped anyway.
        sc_categories = (item.special_collection_categories or "").lower()
        if "indigenous knowledge" in sc_categories:
            resource_type_id = self._resolve_resource_type_id("Indigeneous Knowledge")
        elif "cultural heritage" in sc_categories:
            resource_type_id = self._resolve_resource_type_id("Cultural Heritage")
        else:
            resource_type_id = self._resolve_resource_type_id("Manuscripts")
        author_role_id = self._resolve_creator_role_id("Author")

        fields: list[tuple[str, str]] = [
            ("publicationPoster", ""),
            ("documentDocid", docid),
            ("documentTitle", title),
            ("documentDescription", description),
            ("resourceType", str(resource_type_id)),
            ("user_id", str(self.user_id)),
            ("owner", "URAAS / University of Lagos"),
            ("avatar", ""),
        ]

        # Crawled from OpenAlex funders/awards (uraas.database.Item.funders,
        # JSON [{"name","ror","award_id"}, ...] — see
        # openalex_spider.py._extract_funders). "type" mirrors the literal
        # default (1) the platform's own submit form always sends here.
        funders = []
        if item.funders:
            try:
                funders = json.loads(item.funders)
            except (TypeError, ValueError):
                funders = []
        for i, funder in enumerate(funders):
            fields.extend([
                (f"funders[{i}][name]", funder.get("name", "")),
                (f"funders[{i}][other_name]", ""),
                (f"funders[{i}][type]", "1"),
                (f"funders[{i}][country]", ""),
                (f"funders[{i}][ror_id]", funder.get("ror") or ""),
            ])

        for i, author in enumerate(getattr(item, "authors", [])):
            name = (getattr(author, "name", "") or "").strip()
            if not name:
                continue
            parts = name.rsplit(" ", 1)
            given_name, family_name = (parts[0], parts[1]) if len(parts) == 2 else ("", name)
            orcid = getattr(author, "orcid", "") or ""
            fields.extend([
                (f"creators[{i}][family_name]", family_name),
                (f"creators[{i}][given_name]", given_name),
                (f"creators[{i}][identifier]", "ORCID" if orcid else ""),
                (f"creators[{i}][role]", str(author_role_id)),
                (f"creators[{i}][orcid_id]", orcid),
                (f"creators[{i}][affiliation]", item.institution or ""),
            ])

        # The real endpoint requires actual multipart/form-data (it reads
        # request.formData() server-side, not a JSON body) even though every
        # field here is plain text. requests only multipart-encodes via
        # `files=`, so each field is wrapped as (None, value) — the idiom for
        # "text field via files=" — matching a browser's
        # FormData.append(key, stringValue) byte-for-byte instead of adding
        # any stray placeholder field.
        multipart_fields = [(k, (None, v)) for k, v in fields]
        r = self._s.post(
            f"{self.base}/publications/publish",
            files=multipart_fields,
            timeout=60,
        )
        if r.status_code == 401:
            self.login()
            r = self._s.post(
                f"{self.base}/publications/publish",
                files=multipart_fields,
                timeout=60,
            )
        r.raise_for_status()
        result = r.json()
        result["_assigned_docid"] = docid
        return result
