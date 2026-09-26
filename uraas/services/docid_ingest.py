"""
DOCiD ingest - pulling Africa PID Alliance publications INTO URAAS.

The opposite direction to uraas.services.docid_client, which registers URAAS
records on the DOCiD platform. This reads the platform's own publications so
that everything URAAS does to a record - Special Collections classification,
keyword extraction, framework alignment, the citation graph - can run over
DOCiD's corpus rather than only over the local crawl.

What the API actually allows, verified live against the demo instance
(2026-09-26, https://docid-demo.africapidalliance.org/api/v1):

  GET /publications/get-publications?page&page_size&resource_type_id&sort&order
      -> {data: [...], pagination: {page, page_size, total, total_pages},
          account_type_counts: {...}, resource_type_counts: {...}}
      Unauthenticated. page_size=1000 is accepted (about 5.7s); page_size=100
      takes about 2.4s. Only sort=published works - sort=title returns an
      empty body.

  GET /publications/get-publication/{id}
      -> the full record: creators, organizations, funders, documents,
         abstract, external identifiers. Unauthenticated, about 1.6s.

Three facts drive the design here:

1. There is no `modified_since` or cursor parameter. Incremental sync is
   therefore a newest-first walk (sort=published&order=desc) that stops once
   it reaches records already held, and full backfill is an oldest-first walk
   (order=asc) that is stable under concurrent inserts because new records
   append to the end.

2. The list response omits creators, organisations and the abstract, so one
   detail request per record is mandatory. At roughly 1.6s each that is the
   entire cost of an ingest: about 100 minutes for the demo's 3,726 records
   sequentially, and structurally impossible at corpus scale. Fan the detail
   fetches out across Celery workers (uraas.tasks) rather than looping.

3. The platform advertises no rate limit and returned no 429 under a burst,
   so nothing stops us hammering it except ourselves. Every request here goes
   through _sleep_between(), and the Celery tasks carry an explicit rate
   limit on top.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Iterator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from uraas.config import config
from uraas.database import Author, Item, SessionLocal
from uraas.utils.ai_classifier import sanitize_text

logger = logging.getLogger(__name__)

# DOCiD resource_type_id -> URAAS Item.content_type. Fetched live from
# /publications/get-list-resource-types (2026-09-26); ids are stable platform
# reference data, and an unmapped id falls through to "research_paper" rather
# than failing the record.
RESOURCE_TYPE_TO_CONTENT_TYPE = {
    1: "indigenous_knowledge",  # Indigeneous Knowledge [sic, their spelling]
    2: "patent",  # Patent
    3: "cultural_heritage",  # Cultural Heritage
    4: "research_paper",  # Project
    5: "research_paper",  # Funder
    6: "dataset",  # DMP (Data Management Plan)
    7: "research_paper",  # Manuscripts
    15: "research_paper",  # Book
    16: "thesis",  # Masters Thesis
    17: "thesis",  # PhD Thesis
}


class DocIDIngestError(Exception):
    pass


class DocIDReadClient:
    """Read-only client for the DOCiD publications API.

    Deliberately separate from DocIDClient: that one refuses to do anything
    without DOCID_EMAIL/DOCID_PASSWORD, as a blanket guard against firing an
    unintended live registration, and every endpoint it touches either writes
    or supports a write. Nothing here can write, so nothing here needs that
    gate, and an ingest must not be blocked on registration credentials it
    does not use.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base = (base_url or config.DOCID_INGEST_API_URL).rstrip("/")
        self._s = requests.Session()
        self._s.headers.update(
            {
                "User-Agent": (
                    "URAAS/1.0 (APA Intelligence Platform; " "uraas-bot@unilag.edu.ng)"
                ),
                "Accept": "application/json",
            }
        )
        # Retry the transient failures a long ingest will certainly hit. The
        # platform runs behind nginx with no rate limiting, so 429 is not
        # expected, but honouring it costs nothing if one ever appears.
        retry = Retry(
            total=4,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )
        self._s.mount("https://", HTTPAdapter(max_retries=retry))
        self._last_request_at = 0.0

    def _sleep_between(self):
        delay = config.DOCID_INGEST_DELAY_S
        if delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        self._sleep_between()
        url = f"{self.base}{path}"
        try:
            r = self._s.get(url, params=params, timeout=config.DOCID_INGEST_TIMEOUT_S)
        except requests.RequestException as exc:
            raise DocIDIngestError(f"GET {url} failed: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
        if r.status_code == 404:
            raise DocIDIngestError(f"GET {url} -> 404")
        if r.status_code != 200:
            raise DocIDIngestError(f"GET {url} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def list_publications(
        self,
        page: int = 1,
        page_size: Optional[int] = None,
        order: str = "desc",
        resource_type_id: Optional[int] = None,
    ) -> Dict:
        """One page of the publication index.

        `order` is applied to `published`; it is the only sort the API
        actually honours. "desc" (newest first) is for incremental catch-up,
        "asc" for a stable full backfill.
        """
        params = {
            "page": page,
            "page_size": page_size or config.DOCID_INGEST_PAGE_SIZE,
            "sort": "published",
            "order": order,
        }
        if resource_type_id is not None:
            params["resource_type_id"] = resource_type_id
        return self._get("/publications/get-publications", params)

    def get_publication(self, publication_id) -> Dict:
        """One full record, including creators, organisations and funders."""
        return self._get(f"/publications/get-publication/{publication_id}")

    def total_publications(self) -> int:
        page = self.list_publications(page=1, page_size=1)
        return int((page.get("pagination") or {}).get("total") or 0)

    def iter_publication_ids(
        self,
        order: str = "asc",
        start_page: int = 1,
        max_pages: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Iterator[Dict]:
        """Walk the index, yielding one summary dict per page of records.

        Yields the page envelope rather than individual records so a caller
        can checkpoint by page and hand a whole page to one worker.
        """
        page = start_page
        pages_done = 0
        while True:
            envelope = self.list_publications(
                page=page, page_size=page_size, order=order
            )
            rows = envelope.get("data") or []
            if not rows:
                return
            yield envelope
            pages_done += 1
            pagination = envelope.get("pagination") or {}
            total_pages = int(pagination.get("total_pages") or 0)
            if max_pages and pages_done >= max_pages:
                return
            if total_pages and page >= total_pages:
                return
            page += 1


# -- Mapping DOCiD records onto URAAS's Item ----------------------------------


def _epoch_to_datetime(value) -> Optional[datetime]:
    """DOCiD publishes `published` as a Unix timestamp."""
    try:
        return datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _clean(value: Optional[str]) -> Optional[str]:
    """Strip the HTML the platform stores in free-text fields.

    `description` comes back as "<p>Desc</p>" - it is authored in a rich-text
    editor. sanitize_text is the same cleaner the crawl pipeline uses, so
    ingested records read identically to crawled ones.
    """
    if not value:
        return None
    cleaned = sanitize_text(value)
    return cleaned.strip() or None


def _creator_name(creator: Dict) -> str:
    parts = [
        (creator.get("given_name") or "").strip(),
        (creator.get("family_name") or "").strip(),
    ]
    return " ".join(p for p in parts if p).strip()


def _primary_organization(payload: Dict) -> Dict:
    orgs = payload.get("publication_organizations") or []
    return orgs[0] if orgs else {}


def _org_ror(org: Dict) -> Optional[str]:
    """The ROR from an organisation entry, if that is what it carries.

    Organisations carry `identifier` plus `identifier_type`, and the type can
    be ror, isni, ringgold or rrid - reading `identifier` blindly would file
    an ISNI as a ROR.
    """
    if (org.get("identifier_type") or "").strip().lower() == "ror":
        return org.get("identifier") or None
    return None


def map_publication(payload: Dict) -> Dict:
    """Flatten one DOCiD record into URAAS Item fields plus its people.

    Returns {"item": {...column values...}, "creators": [...],
    "organizations": [...]}. Pure - no database, no network - so the mapping
    is testable against a recorded payload.
    """
    remote_id = payload.get("id")
    title = _clean(payload.get("document_title")) or "(untitled)"
    # abstract_text is the real abstract; document_description is the
    # submitter's free-text blurb. Prefer the former, fall back to the latter,
    # because a great many records carry only one of the two.
    abstract = _clean(payload.get("abstract_text")) or _clean(
        payload.get("document_description")
    )

    org = _primary_organization(payload)
    ror = _org_ror(org)
    published_at = _epoch_to_datetime(payload.get("published"))
    handle_url = payload.get("handle_url") or None
    doi = (payload.get("doi") or "").strip() or None

    item = {
        "title": title[:512],
        "dc_title": title[:512],
        "abstract": abstract,
        "doi": doi,
        "dc_identifier_doi": doi,
        # handle_url is the record's canonical landing page where one exists.
        # Records without it still need a unique url, so they fall back to the
        # platform's own permalink for the publication.
        "url": handle_url or f"{config.DOCID_INGEST_API_URL}/publications/{remote_id}",
        "dc_identifier_uri": handle_url,
        "publication_date": published_at,
        "dc_date_issued": published_at.strftime("%Y-%m-%d") if published_at else None,
        "source_repository": config.DOCID_SOURCE_LABEL,
        "source_record_id": str(remote_id) if remote_id is not None else None,
        "docid": (payload.get("document_docid") or "").strip() or None,
        "content_type": RESOURCE_TYPE_TO_CONTENT_TYPE.get(
            payload.get("resource_type_id"), "research_paper"
        ),
        "institution": (payload.get("owner") or org.get("name") or "").strip() or None,
        "ror": ror,
        "dc_subject": _clean(payload.get("collection_name")),
        "openalex_id": (payload.get("openalex_id") or "").strip() or None,
        "cited_by_count": int(payload.get("citation_count") or 0),
        "pdf_url": payload.get("open_access_url") or None,
        # A Handle from the source repository is authoritative for this
        # record; URAAS must not mint an ARK over the top of one.
        "pid_source": "handle" if handle_url else None,
    }

    oa_status = (payload.get("open_access_status") or "").strip().lower()
    if oa_status and oa_status not in ("closed", "unknown"):
        item["dc_rights"] = "info:eu-repo/semantics/openAccess"

    creators = []
    for creator in payload.get("publication_creators") or []:
        name = _creator_name(creator)
        if not name:
            continue
        identifier_type = (creator.get("identifier_type") or "").strip().lower()
        creators.append(
            {
                "name": name,
                "orcid": (
                    creator.get("identifier") if identifier_type == "orcid" else None
                ),
                "affiliation": creator.get("affiliation") or None,
            }
        )

    organizations = [
        {
            "name": o.get("name"),
            "ror": _org_ror(o),
            "isni": o.get("isni") or None,
            "country": o.get("country") or None,
        }
        for o in payload.get("publication_organizations") or []
        if o.get("name")
    ]

    return {"item": item, "creators": creators, "organizations": organizations}


# -- Persistence ---------------------------------------------------------------


def _find_existing(session, fields: Dict) -> Optional[Item]:
    """Locate a record already held for this DOCiD publication.

    Matched on (source_repository, source_record_id) first: that pair is the
    only stable external identity, and it is what makes re-ingest idempotent
    rather than duplicating. DOI and url are fallbacks for a record URAAS
    already crawled from elsewhere, so an ingest enriches it instead of
    creating a second copy of the same paper.
    """
    source_id = fields.get("source_record_id")
    if source_id:
        row = (
            session.query(Item)
            .filter(
                Item.source_repository == fields["source_repository"],
                Item.source_record_id == source_id,
            )
            .first()
        )
        if row:
            return row
    if fields.get("doi"):
        row = session.query(Item).filter(Item.doi == fields["doi"]).first()
        if row:
            return row
    if fields.get("url"):
        return session.query(Item).filter(Item.url == fields["url"]).first()
    return None


def _attach_authors(session, item: Item, creators: List[Dict], ror: Optional[str]):
    """Link creators to the item, reusing Author rows.

    Matched on normalized_name (lower-cased) exactly as
    uraas.pipelines.database does, and for the same reason: a different
    matching rule here would split one person into two Author rows across the
    crawled and ingested halves of the corpus, quietly halving their
    publication count and h-index. normalized_name is also NOT NULL, so it
    has to be set explicitly rather than left to a default.

    Name matching conflates genuine namesakes. ORCID would be the correct
    key, but only a minority of DOCiD creators carry one, and changing the
    rule for ingested records alone is exactly the split this avoids.
    """
    existing = {(a.normalized_name or "").strip() for a in item.authors}
    for creator in creators:
        name = creator["name"].strip()
        if not name:
            continue
        norm = name.lower()
        author = session.query(Author).filter(Author.normalized_name == norm).first()
        if not author:
            author = Author(
                name=name,
                normalized_name=norm,
                orcid=creator.get("orcid") or "",
                ror=ror or "",
            )
            session.add(author)
            session.flush()
        else:
            if creator.get("orcid") and not author.orcid:
                author.orcid = creator["orcid"]
            if ror and not author.ror:
                author.ror = ror
        if norm not in existing:
            item.authors.append(author)
            existing.add(norm)


def upsert_publication(payload: Dict, session=None) -> Dict:
    """Store one DOCiD record, creating or updating as appropriate.

    Returns {"item_id", "action", "source_record_id"} where action is
    "created", "updated" or "skipped".
    """
    mapped = map_publication(payload)
    fields = mapped["item"]
    owns_session = session is None
    session = session or SessionLocal()
    try:
        existing = _find_existing(session, fields)
        if existing:
            for key, value in fields.items():
                # Never blank an existing value with a null from DOCiD: a
                # record URAAS crawled from OpenAlex may carry an abstract,
                # a DOI or a citation count that the DOCiD copy lacks, and
                # ingest is meant to add to a record, not hollow it out.
                if value in (None, "", 0) and getattr(existing, key, None):
                    continue
                setattr(existing, key, value)
            _attach_authors(session, existing, mapped["creators"], fields.get("ror"))
            action = "updated"
            item = existing
        else:
            item = Item(**fields)
            session.add(item)
            session.flush()
            _attach_authors(session, item, mapped["creators"], fields.get("ror"))
            action = "created"

        if owns_session:
            session.commit()
        return {
            "item_id": item.id,
            "action": action,
            "source_record_id": fields.get("source_record_id"),
        }
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def ingest_record(publication_id, client: Optional[DocIDReadClient] = None) -> Dict:
    """Fetch and store one publication by its DOCiD id."""
    client = client or DocIDReadClient()
    payload = client.get_publication(publication_id)
    return upsert_publication(payload)


def known_source_ids(source_label: Optional[str] = None) -> set:
    """Every DOCiD id already held, for the incremental walk's stop test."""
    label = source_label or config.DOCID_SOURCE_LABEL
    session = SessionLocal()
    try:
        rows = (
            session.query(Item.source_record_id)
            .filter(
                Item.source_repository == label,
                Item.source_record_id.isnot(None),
            )
            .all()
        )
        return {r[0] for r in rows}
    finally:
        session.close()


def ingest_coverage(
    source_label: Optional[str] = None, probe_remote: bool = True
) -> Dict:
    """How much of the DOCiD corpus URAAS holds.

    Reports the remote total alongside the local count, because "we have
    3,000 records" means nothing without knowing whether the source has 3,726
    or three million.

    `probe_remote=False` answers from the local database alone. The remote
    half costs a live call to the platform, which is the wrong thing to do
    on a dashboard poll or in a test.
    """
    from sqlalchemy import func

    label = source_label or config.DOCID_SOURCE_LABEL
    session = SessionLocal()
    try:
        held = (
            session.query(func.count(Item.id))
            .filter(Item.source_repository == label)
            .scalar()
            or 0
        )
        with_authors = (
            session.query(func.count(func.distinct(Item.id)))
            .filter(Item.source_repository == label)
            .join(Item.authors)
            .scalar()
            or 0
        )
    finally:
        session.close()

    result = {
        "source": label,
        "api_url": config.DOCID_INGEST_API_URL,
        "records_held": held,
        "records_with_creators": with_authors,
        "remote_total": None,
        "coverage_pct": None,
    }
    if not probe_remote:
        return result
    try:
        remote = DocIDReadClient().total_publications()
        result["remote_total"] = remote
        if remote:
            result["coverage_pct"] = round(held / remote * 100, 1)
    except DocIDIngestError as exc:
        # A coverage read must not fail just because the remote is down; the
        # local half of the answer is still worth returning.
        result["remote_error"] = str(exc)
    return result
