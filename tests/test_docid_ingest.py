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
