"""Tests for the DOCiD ingest.

Every payload here is a real response recorded from the demo instance
(tests/fixtures/docid_*.json, captured 2026-09-26), so the mapping is tested
against what the platform actually returns rather than against an invented
shape. Nothing in this file makes a network call - the read client is only
exercised through the fixtures, because a test suite that depends on a third
party being up is a test suite that fails for reasons that are not our bug.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config import config  # noqa: E402
from uraas.database import Item, SessionLocal  # noqa: E402
from uraas.services.docid_ingest import (  # noqa: E402
    RESOURCE_TYPE_TO_CONTENT_TYPE,
    _clean,
    _epoch_to_datetime,
    _org_ror,
    ingest_coverage,
    map_publication,
    upsert_publication,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def dspace_record():
    """A DSpace-harvested record: five creators, a ROR-bearing organisation,
    a handle_url, and no DOI."""
    return _fixture("docid_publication_4185.json")


@pytest.fixture
def minimal_record():
    """A recent hand-entered record: one creator, HTML in the description."""
    return _fixture("docid_publication_5253.json")


@pytest.fixture
def index_page():
    return _fixture("docid_publications_page.json")


# -- Helpers ---------------------------------------------------------------


def test_epoch_conversion():
    assert _epoch_to_datetime(1788954245).year == 2026
    assert _epoch_to_datetime(None) is None
    assert _epoch_to_datetime("not-a-number") is None


def test_clean_strips_the_html_the_platform_stores():
    # Free-text fields are authored in a rich-text editor and come back as
    # markup, which must not reach the database as literal tags.
    assert "<p>" not in (_clean("<p>Describe </p>") or "")
    assert _clean("") is None
    assert _clean(None) is None


def test_org_ror_refuses_identifiers_that_are_not_rors():
    """identifier_type decides what identifier holds.

    Organisations carry ror, isni, ringgold or rrid in the same field, so
    reading it blindly would file an ISNI as a ROR and corrupt every
    institution-level metric that groups on ror.
    """
    assert _org_ror({"identifier_type": "ror", "identifier": "https://ror.org/x"}) == (
        "https://ror.org/x"
    )
    assert _org_ror({"identifier_type": "isni", "identifier": "0000 0001"}) is None
    assert _org_ror({"identifier": "https://ror.org/x"}) is None
    assert _org_ror({}) is None


# -- Mapping ---------------------------------------------------------------


def test_maps_a_dspace_record(dspace_record):
    mapped = map_publication(dspace_record)
    item = mapped["item"]

    assert item["source_record_id"] == "4185"
    assert item["source_repository"] == config.DOCID_SOURCE_LABEL
    assert item["title"].startswith("Skills and Literacy Training")
    assert item["institution"] == "University of Nairobi"
    assert item["ror"] == "https://ror.org/02y9nww90"
    assert item["docid"] == "uon/0ed2b8a0-3a5e-4b27-a761-24604ee90bd4"
    assert item["url"].startswith("https://erepository.uonbi.ac.ke/")
    # The source repository already assigned a Handle, so URAAS must not
    # mint an ARK over the top of one.
    assert item["pid_source"] == "handle"
    assert item["content_type"] == "indigenous_knowledge"
    assert len(mapped["creators"]) == 5
    assert {"Oxenham", "Diallo"} <= {c["name"].split()[-1] for c in mapped["creators"]}


def test_maps_a_record_without_a_handle(minimal_record):
    item = map_publication(minimal_record)["item"]
    # Item.url is unique and NOT optional, so a record with no landing page
    # still needs one or the insert fails.
    assert item["url"]
    assert item["source_record_id"] == "5253"
    assert item["pid_source"] is None


def test_title_is_never_empty():
    """Item.title is NOT NULL, and the platform does allow blank titles."""
    item = map_publication({"id": 1, "document_title": None})["item"]
    assert item["title"]


def test_title_is_truncated_to_the_column_width():
    item = map_publication({"id": 1, "document_title": "x" * 900})["item"]
    assert len(item["title"]) <= 512
    assert len(item["dc_title"]) <= 512


def test_unknown_resource_type_falls_back_rather_than_failing():
    item = map_publication({"id": 1, "resource_type_id": 99999})["item"]
    assert item["content_type"] == "research_paper"


def test_every_mapped_content_type_is_one_uraas_uses():
    # Item.content_type feeds the TK Vitality Score, which buckets on these
    # exact strings; a typo here would silently drop records from it.
    allowed = {
        "research_paper",
        "thesis",
        "patent",
        "indigenous_knowledge",
        "cultural_heritage",
        "oral_tradition",
        "dataset",
        "grey_literature",
    }
    assert set(RESOURCE_TYPE_TO_CONTENT_TYPE.values()) <= allowed


def test_abstract_prefers_the_real_abstract_over_the_blurb():
    both = map_publication(
        {
            "id": 1,
            "abstract_text": "The abstract",
            "document_description": "<p>blurb</p>",
        }
    )["item"]
    assert both["abstract"] == "The abstract"
    only_blurb = map_publication({"id": 1, "document_description": "<p>blurb</p>"})[
        "item"
    ]
    assert only_blurb["abstract"] == "blurb"


def test_mapping_is_pure(dspace_record):
    """No database, no network - so the mapping stays testable offline."""
    before = json.dumps(dspace_record, sort_keys=True)
    map_publication(dspace_record)
    assert json.dumps(dspace_record, sort_keys=True) == before


# -- Persistence -----------------------------------------------------------


def test_upsert_is_idempotent(dspace_record):
    """Re-ingesting must update, never duplicate.

    (source_repository, source_record_id) is the only stable identity
    available: Item.id is reused by SQLite after a delete, and this record
    has no DOI at all.
    """
    first = upsert_publication(dspace_record)
    second = upsert_publication(dspace_record)
    assert first["item_id"] == second["item_id"]
    assert second["action"] == "updated"

    session = SessionLocal()
    try:
        count = (
            session.query(Item)
            .filter(
                Item.source_repository == config.DOCID_SOURCE_LABEL,
                Item.source_record_id == "4185",
            )
            .count()
        )
    finally:
        session.close()
    assert count == 1


def test_upsert_attaches_creators_once(dspace_record):
    upsert_publication(dspace_record)
    upsert_publication(dspace_record)
    session = SessionLocal()
    try:
        item = (
            session.query(Item)
            .filter(
                Item.source_repository == config.DOCID_SOURCE_LABEL,
                Item.source_record_id == "4185",
            )
            .first()
        )
        names = [a.name for a in item.authors]
    finally:
        session.close()
    assert len(names) == len(set(names)), "authors duplicated across ingests"
    assert len(names) >= 5


def test_upsert_never_blanks_an_existing_value(dspace_record):
    """Ingest enriches a record; it must not hollow one out.

    A paper URAAS already crawled from OpenAlex can carry an abstract, a DOI
    or a citation count that the DOCiD copy lacks. Writing the DOCiD nulls
    over the top would destroy data on every sync.
    """
    upsert_publication(dspace_record)
    session = SessionLocal()
    try:
        item = (
            session.query(Item)
            .filter(Item.source_record_id == "4185")
            .filter(Item.source_repository == config.DOCID_SOURCE_LABEL)
            .first()
        )
        item.abstract = "An abstract URAAS already had"
        item.cited_by_count = 42
        session.commit()
        item_id = item.id
    finally:
        session.close()

    # The fixture carries abstract_text: null and citation_count: null.
    assert dspace_record["abstract_text"] is None
    assert dspace_record["citation_count"] is None
    upsert_publication(dspace_record)

    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == item_id).first()
        assert item.abstract == "An abstract URAAS already had"
        assert item.cited_by_count == 42
    finally:
        session.close()


def test_ingested_records_are_distinguishable_from_the_local_crawl(dspace_record):
    upsert_publication(dspace_record)
    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.source_record_id == "4185").first()
    finally:
        session.close()
    assert item.source_repository == config.DOCID_SOURCE_LABEL
    assert "DOCiD" in item.source_repository


def test_ingest_coverage_reports_the_local_half_without_the_remote(monkeypatch):
    """Coverage must still answer when the platform is unreachable."""
    import uraas.services.docid_ingest as ingest

    class Unreachable:
        def total_publications(self):
            raise ingest.DocIDIngestError("connection refused")

    monkeypatch.setattr(ingest, "DocIDReadClient", lambda *a, **k: Unreachable())
    cov = ingest.ingest_coverage()
    assert cov["records_held"] >= 0
    assert cov["remote_total"] is None
    assert "remote_error" in cov


def test_coverage_can_skip_the_remote_probe_entirely(monkeypatch):
    """probe_remote=False must not construct a client at all.

    A dashboard polling coverage should not make a third-party call on every
    refresh, and neither should a test.
    """
    import uraas.services.docid_ingest as ingest

    def explode(*a, **k):
        raise AssertionError("probe_remote=False must not touch the network")

    monkeypatch.setattr(ingest, "DocIDReadClient", explode)
    cov = ingest.ingest_coverage(probe_remote=False)
    assert cov["remote_total"] is None
    assert "remote_error" not in cov


# -- Index page shape ------------------------------------------------------


def test_index_page_carries_the_pagination_the_backfill_relies_on(index_page):
    pagination = index_page["pagination"]
    for field in ("page", "page_size", "total", "total_pages"):
        assert field in pagination
    assert index_page["data"]


def test_index_rows_lack_the_fields_that_force_a_detail_call(index_page):
    """Documents the reason the ingest costs one request per record.

    If the platform ever adds creators and abstracts to the list response,
    this test fails and the ingest can be collapsed to one request per page,
    which is the difference between weeks and hours at corpus scale.
    """
    row = index_page["data"][0]
    assert "publication_creators" not in row
    assert "publication_organizations" not in row
    assert "abstract_text" not in row
    # What the list DOES give, and what the backfill therefore relies on.
    for field in ("id", "title", "published", "resource_type_id"):
        assert field in row


# -- Celery wiring ---------------------------------------------------------


def test_tasks_are_registered():
    from uraas.tasks import celery_app

    for name in (
        "uraas.docid.backfill",
        "uraas.docid.incremental",
        "uraas.docid.ingest_page",
        "uraas.docid.ingest_record",
    ):
        assert name in celery_app.tasks


def test_redis_url_is_not_treated_as_a_broker(monkeypatch):
    """REDIS_URL is the analytics cache, not the queue.

    It is set on developer machines where nothing is listening. Inheriting
    it would make .delay() queue work into a Redis that does not exist: the
    task vanishes and the caller is told it was accepted.
    """
    import uraas.tasks as tasks

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(tasks.config, "CELERY_BROKER_URL", "")
    assert tasks._broker_url() == ""


def test_queue_status_does_not_leak_the_broker_credentials(monkeypatch):
    import uraas.tasks as tasks

    monkeypatch.setattr(tasks, "BROKER_URL", "redis://:hunter2@redis:6379/1")
    status = tasks.queue_status()
    assert status["broker_scheme"] == "redis"
    assert "hunter2" not in json.dumps(status)


def test_eager_mode_when_no_broker_is_configured():
    """The Hugging Face Space has one gunicorn worker and no Redis, so the
    ingest has to remain callable without a queue - just synchronously."""
    import uraas.tasks as tasks

    if tasks.BROKER_URL:
        pytest.skip("a broker is configured in this environment")
    assert tasks.EAGER
    assert tasks.celery_app.conf.task_always_eager


# -- HTTP surface ----------------------------------------------------------


def test_ingest_coverage_endpoint(admin_client):
    # ?remote=0 keeps this off the network: the remote half of coverage is a
    # live call to a third party, and a suite that fails when their server
    # is down is a suite that fails for reasons that are not our bug.
    r = admin_client.get("/api/docid/ingest/coverage?remote=0")
    assert r.status_code == 200
    body = r.get_json()
    assert "records_held" in body
    assert "queue" in body
    assert body["remote_total"] is None


def test_unbounded_backfill_is_refused_without_a_broker(admin_client):
    """An unbounded eager backfill would run one upstream request per record
    inside the request thread. Refusing beats hanging."""
    import uraas.tasks as tasks

    if tasks.BROKER_URL:
        pytest.skip("a broker is configured in this environment")
    r = admin_client.post("/api/admin/docid/ingest/backfill", json={})
    assert r.status_code == 400
    assert "broker" in r.get_json()["message"].lower()


def test_ingest_writes_stay_admin_only():
    from uraas.dashboard.app import ADMIN_ENDPOINTS, PARTNER_ENDPOINTS

    for endpoint in (
        "admin_docid_backfill",
        "admin_docid_incremental",
        "admin_docid_ingest_record",
    ):
        assert endpoint in ADMIN_ENDPOINTS
        assert endpoint not in PARTNER_ENDPOINTS
    assert "docid_ingest_coverage" in PARTNER_ENDPOINTS


def test_viewer_cannot_start_an_ingest(viewer_client):
    assert (
        viewer_client.post(
            "/api/admin/docid/ingest/incremental", json={"max_pages": 1}
        ).status_code
        == 403
    )
    assert (
        viewer_client.post("/api/admin/docid/ingest/backfill", json={}).status_code
        == 403
    )


# -- Circular-ingest guard -------------------------------------------------


def test_partner_requests_exclude_ingested_sources():
    """A DOCiD record must never be served back to DOCiD.

    DOCiD pulls records from URAAS, and URAAS now ingests records from DOCiD.
    Without a guard, a DOCiD record would come back to them through the
    partner API and be re-ingested as though it were a UNILAG record, with
    each side crediting the other as the source and no way to tell afterwards
    which of them actually holds it.
    """
    from flask import g

    from uraas.dashboard.app import _partner_excluded_sources, app

    with app.test_request_context("/api/papers/tree"):
        # A browser session sees everything - looking at the ingested corpus
        # is the entire point of ingesting it.
        assert _partner_excluded_sources() is None

    with app.test_request_context("/api/papers/tree"):
        g.partner_name = "Africa PID Alliance / DOCiD"
        assert "DOCiD" in _partner_excluded_sources()


def test_exclusion_matches_every_docid_environment_label():
    """One rule has to cover demo and production.

    The label is part of a record's identity, so the two environments carry
    different ones; matching the exact string would let production records
    leak once someone switched DOCID_SOURCE_LABEL.
    """
    from uraas.dashboard.app import PARTNER_EXCLUDED_SOURCE_PREFIXES

    for label in ("DOCiD (demo)", "DOCiD (production)", "DOCiD"):
        assert any(label.startswith(p) for p in PARTNER_EXCLUDED_SOURCE_PREFIXES)
    # ...without swallowing the local crawl.
    for label in ("UNILAG IR (OAI-PMH)", "OpenAlex", "Crossref"):
        assert not any(label.startswith(p) for p in PARTNER_EXCLUDED_SOURCE_PREFIXES)


def test_exclude_sources_filters_the_query(dspace_record):
    """The filter must actually drop ingested rows, not just be plumbed in."""
    from sqlalchemy import or_

    from uraas.analytics.engine import analytics

    upsert_publication(dspace_record)
    session = SessionLocal()
    try:
        total = session.query(Item).count()
        kept = (
            session.query(Item)
            .filter(
                or_(
                    Item.source_repository.is_(None),
                    ~Item.source_repository.startswith("DOCiD"),
                )
            )
            .count()
        )
    finally:
        session.close()
    assert kept < total, "the ingested record was not excluded"

    # And the analytics entry point accepts the argument the partner path
    # passes, rather than silently ignoring an unknown keyword.
    assert isinstance(
        analytics.get_papers_by_faculty_and_department(exclude_sources=["DOCiD"]),
        dict,
    )


# -- Enrichment: what DOCiD actually consumes ------------------------------


def test_ingest_populates_keywords(dspace_record):
    """Keywords must be on the record at ingest, not filled in lazily later.

    Lazy extraction is fine for a record someone opens in the dashboard. It is
    wrong for a corpus served as a bulk feed, where every record would come
    back empty until something happened to touch it one at a time.
    """
    from uraas.services.docid_ingest import keywords_for

    result = upsert_publication(dspace_record)
    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == result["item_id"]).first()
        stored = item.ai_keywords
    finally:
        session.close()
    assert stored, "ingest left ai_keywords empty"
    assert len(stored.split(",")) > 1

    assert keywords_for(None, None) is None
    assert keywords_for("Sacred landscapes and indigenous geoconservation", None)


def test_enrichment_is_addressed_by_docid_own_id(dspace_record):
    """DOCiD knows publication 4185, not URAAS item 58.

    (source_repository, source_record_id) is what makes their id addressable,
    which is the reason that column exists.
    """
    from uraas.services.docid_ingest import enrichment_by_source_id

    upsert_publication(dspace_record)
    data = enrichment_by_source_id(4185)
    assert data is not None
    assert data["docid_publication_id"] == "4185"
    assert data["uraas_item_id"]
    assert isinstance(data["keywords"], list)


def test_enrichment_returns_none_for_an_uningested_record():
    from uraas.services.docid_ingest import enrichment_by_source_id

    assert enrichment_by_source_id(999999999) is None


def test_citations_say_why_they_are_empty(dspace_record):
    """An empty edge list must not read as "no citations".

    Only 1.8% of this corpus carries a DOI and ~2% an OpenAlex id (measured
    2026-09-28), and 99.6% is Cultural Heritage or Indigenous Knowledge,
    which citation databases do not index at all. Without an explicit
    `available: false`, a consumer cannot tell "uncited" from "not a citable
    record type".
    """
    from uraas.services.docid_ingest import enrichment_by_source_id

    assert not (dspace_record.get("doi") or "").strip()
    upsert_publication(dspace_record)
    citations = enrichment_by_source_id(4185)["citations"]
    assert citations["available"] is False
    assert "no DOI or OpenAlex id" in citations["reason"]
    assert citations["citing"] == []


def test_bulk_feed_is_paginated_and_stable(dspace_record, minimal_record):
    """Ordered by source_record_id so paging does not shuffle while more
    records are still being ingested."""
    from uraas.services.docid_ingest import enrichment_page

    upsert_publication(dspace_record)
    upsert_publication(minimal_record)
    page = enrichment_page(page=1, page_size=1)
    assert page["pagination"]["page_size"] == 1
    assert page["pagination"]["total"] >= 2
    assert len(page["data"]) == 1

    ids = []
    for p in (1, 2):
        ids += [
            r["docid_publication_id"]
            for r in enrichment_page(page=p, page_size=1)["data"]
        ]
    assert ids == sorted(ids), "bulk feed is not ordered stably"
    assert len(set(ids)) == len(ids), "a record appeared on two pages"


def test_bulk_feed_omits_citations_by_default(dspace_record):
    """Citations are a per-record read that is empty for most of this corpus;
    including them by default makes a page of 100 slower for no benefit."""
    from uraas.services.docid_ingest import enrichment_page

    upsert_publication(dspace_record)
    assert "citations" not in enrichment_page(page=1, page_size=5)["data"][0]
    with_c = enrichment_page(page=1, page_size=5, include_citations=True)
    assert "citations" in with_c["data"][0]


def test_enrichment_endpoints_are_partner_readable():
    """DOCiD consumes these with their partner key, so they must be on the
    allowlist and must not be admin-gated."""
    from uraas.dashboard.app import ADMIN_ENDPOINTS, PARTNER_ENDPOINTS

    for endpoint in ("docid_enrichment_one", "docid_enrichment_bulk"):
        assert endpoint in PARTNER_ENDPOINTS
        assert endpoint not in ADMIN_ENDPOINTS


def test_enrichment_http_surface(admin_client, dspace_record):
    upsert_publication(dspace_record)
    r = admin_client.get("/api/docid/enrichment/4185")
    assert r.status_code == 200
    assert r.get_json()["docid_publication_id"] == "4185"

    assert admin_client.get("/api/docid/enrichment/999999999").status_code == 404

    b = admin_client.get("/api/docid/enrichment?page=1&page_size=2")
    assert b.status_code == 200
    body = b.get_json()
    assert "pagination" in body and "data" in body
    assert len(body["data"]) <= 2


# -- Auto-sync: keeping the corpus current without a scheduler -------------


def test_auto_sync_is_off_unless_asked_for():
    """It sends recurring traffic to a third party's API, so no deployment
    inherits it by accident."""
    import uraas.dashboard.app as app_module

    if app_module.config.DOCID_AUTO_SYNC:
        pytest.skip("auto-sync explicitly enabled in this environment")
    assert app_module.start_docid_auto_sync() is False
    assert app_module._docid_auto_sync_started is False


def test_auto_sync_starts_at_most_once_per_process(monkeypatch):
    """gunicorn imports the module once per worker; a second call must not
    add a second thread hitting the same API twice as often."""
    import uraas.dashboard.app as app_module

    started = []
    monkeypatch.setattr(app_module.config, "DOCID_AUTO_SYNC", True)
    monkeypatch.setattr(app_module, "_docid_auto_sync_started", False)

    class FakeThread:
        def __init__(self, *a, **k):
            started.append(k.get("name"))

        def start(self):
            pass

    monkeypatch.setattr(app_module.threading, "Thread", FakeThread)
    assert app_module.start_docid_auto_sync() is True
    assert app_module.start_docid_auto_sync() is False
    assert started == ["docid-auto-sync"]


def test_coverage_reports_whether_auto_sync_is_running(admin_client):
    """An operator has to be able to tell a live corpus from a frozen one."""
    body = admin_client.get("/api/docid/ingest/coverage?remote=0").get_json()
    assert "auto_sync" in body
    for field in ("enabled", "running", "interval_s", "runs", "last_error"):
        assert field in body["auto_sync"]


def test_incremental_only_ever_sees_new_records():
    """Documents the limit, so nobody assumes edits propagate.

    The API has no modified_since filter and only sort=published works, so
    the walk is newest-first against a watermark. A record edited in place
    keeps its original published timestamp and never resurfaces.
    """
    import inspect

    from uraas.tasks import docid_incremental

    doc = inspect.getdoc(docid_incremental) or ""
    assert "new" in doc.lower()
    assert "modified_since" in doc or "modified since" in doc.lower()


# -- Holding more than one DOCiD instance ----------------------------------
#
# Every case here was a live defect found on 2026-09-29 by pointing the
# ingest at docid-core while a docid-demo corpus was already held.


def _as_production(payload):
    """The same publication as it appears on the production instance."""
    return dict(payload)


def test_a_second_source_cannot_steal_the_first_sources_record(dspace_record):
    """The DOI/url fallback must not re-label another source's record.

    Demo and production share handle URLs and DOIs for the same underlying
    work. Without this guard, ingesting production over a demo corpus
    rewrote source_repository and source_record_id in place, and the demo
    corpus silently stopped being addressable.
    """
    import uraas.services.docid_ingest as di

    first = upsert_publication(dspace_record)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(di.config, "DOCID_SOURCE_LABEL", "DOCiD (production)")
        second = upsert_publication(_as_production(dspace_record))

    assert second["item_id"] != first["item_id"], "production stole the demo record"

    session = SessionLocal()
    try:
        labels = {
            r.source_repository
            for r in session.query(Item).filter(Item.source_record_id == "4185").all()
        }
    finally:
        session.close()
    assert labels == {config.DOCID_SOURCE_LABEL, "DOCiD (production)"}


def test_a_shared_handle_url_does_not_fail_the_record(dspace_record):
    """Item.url is UNIQUE and both instances carry the same handle.

    Refusing to steal the record is not enough on its own - the insert then
    violated the unique constraint and failed four records in five. The
    duplicate falls back to its own instance permalink instead.
    """
    import uraas.services.docid_ingest as di

    assert dspace_record.get("handle_url")
    upsert_publication(dspace_record)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(di.config, "DOCID_SOURCE_LABEL", "DOCiD (production)")
        result = upsert_publication(
            _as_production(dspace_record),
            api_base="https://docid-core.africapidalliance.org/api/v1",
        )

    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == result["item_id"]).first()
        url, uri, docid = item.url, item.dc_identifier_uri, item.docid
    finally:
        session.close()
    assert "docid-core" in url, "duplicate did not fall back to its own permalink"
    # The real landing page must survive on the duplicate, not be thrown away.
    assert uri == dspace_record["handle_url"]
    # docid is UNIQUE and the first copy claimed it.
    assert docid is None


def test_provenance_url_names_the_instance_the_record_came_from():
    """Reading the global config here recorded a docid-demo URL on a record
    fetched from docid-core."""
    from uraas.services.docid_ingest import map_publication

    payload = {"id": 99, "document_title": "no handle here"}
    core = map_publication(
        payload, api_base="https://docid-core.africapidalliance.org/api/v1"
    )["item"]
    assert "docid-core" in core["url"]
    demo = map_publication(
        payload, api_base="https://docid-demo.africapidalliance.org/api/v1"
    )["item"]
    assert "docid-demo" in demo["url"]
    assert core["url"] != demo["url"]


def test_each_instance_stays_separately_addressable(dspace_record):
    import uraas.services.docid_ingest as di

    upsert_publication(dspace_record)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(di.config, "DOCID_SOURCE_LABEL", "DOCiD (production)")
        upsert_publication(
            _as_production(dspace_record),
            api_base="https://docid-core.africapidalliance.org/api/v1",
        )

    for label in (config.DOCID_SOURCE_LABEL, "DOCiD (production)"):
        found = di.enrichment_by_source_id(4185, source_label=label)
        assert found is not None, f"{label} corpus not addressable"
        assert found["docid_publication_id"] == "4185"


# -- Dashboard visibility --------------------------------------------------


def test_ingest_classifies_for_special_collections(dspace_record):
    """Every dashboard view gates on SC_FILTER (special_collection_score > 0).

    Item.special_collection_score defaults to 0.0, so a record that is never
    classified is stored correctly, served correctly by the API, and
    invisible in the UI. Ingest did exactly that: 3,726 records were held and
    none appeared anywhere on the dashboard.
    """
    result = upsert_publication(dspace_record)
    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == result["item_id"]).first()
        score, cats = item.special_collection_score, item.special_collection_categories
    finally:
        session.close()
    # This fixture is a Cultural Heritage / Traditional Knowledge record.
    assert score > 0, "ingested record was not classified"
    assert cats


def test_classification_uses_the_same_engine_as_the_crawl():
    """An ingested record must be ranked on the same basis as a crawled one,
    not by a second, looser rule."""
    from uraas.services.docid_ingest import classify_special_collection
    from uraas.services.sc_engine import is_special_collection

    fields = {
        "title": "Indigenous knowledge and traditional healing practices",
        "abstract": "Traditional medicine and indigenous knowledge systems.",
        "dc_subject": "Cultural Heritage; Traditional Knowledge",
    }
    mine = classify_special_collection(fields)
    is_sc, score, _ = is_special_collection(
        fields["title"], fields["abstract"], fields["dc_subject"]
    )
    assert mine["special_collection_score"] == (score if is_sc else 0.0)


def test_classification_never_invents_a_score():
    """A record with no usable text must score 0 rather than be forced in."""
    from uraas.services.docid_ingest import classify_special_collection

    assert (
        classify_special_collection({"title": "", "abstract": "", "dc_subject": ""})[
            "special_collection_score"
        ]
        == 0.0
    )


def test_reclassify_never_deletes(dspace_record, minimal_record):
    """scripts/reclassify_and_prune_sc.py deletes everything scoring 0.

    That is right for the UNILAG crawl, which is Special-Collections-only,
    and badly wrong for a partner corpus: roughly two thirds of DOCiD's
    records score 0 because they genuinely are not African
    indigenous-knowledge material, and they still need their keywords served.
    """
    from uraas.services.docid_ingest import reclassify_ingested

    upsert_publication(dspace_record)
    upsert_publication(minimal_record)
    session = SessionLocal()
    try:
        before = (
            session.query(Item)
            .filter(Item.source_repository == config.DOCID_SOURCE_LABEL)
            .count()
        )
    finally:
        session.close()

    stats = reclassify_ingested()

    session = SessionLocal()
    try:
        after = (
            session.query(Item)
            .filter(Item.source_repository == config.DOCID_SOURCE_LABEL)
            .count()
        )
    finally:
        session.close()
    assert after == before, "reclassify deleted records"
    assert stats["scanned"] == before


def test_reclassify_stays_admin_only():
    from uraas.dashboard.app import ADMIN_ENDPOINTS, PARTNER_ENDPOINTS

    assert "admin_docid_reclassify" in ADMIN_ENDPOINTS
    assert "admin_docid_reclassify" not in PARTNER_ENDPOINTS
