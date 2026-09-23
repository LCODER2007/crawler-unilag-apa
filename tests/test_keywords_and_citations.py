"""Tests for the keyword service and the citation-graph side of the citation
tracker.

Everything here runs against whatever is in the test database and skips when
there is nothing suitable, rather than asserting on corpus contents: the two
services are read/repair layers over existing records, so a fixed expectation
about "paper 1" would only ever assert that the fixture data had not changed.
No test in this file makes a network call - the OpenAlex fetchers are
exercised through their identity helpers and their persistence path, not by
hitting the API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Item, SessionLocal  # noqa: E402
from uraas.services import keyword_service as ks  # noqa: E402
from uraas.services.citation_tracker import (  # noqa: E402
    Citation,
    CitationTracker,
    edge_key,
    get_citation_graph_coverage,
    get_paper_citations,
    normalise_doi,
    short_openalex_id,
)


def _any_item_id():
    session = SessionLocal()
    try:
        row = session.query(Item.id).first()
        return row[0] if row else None
    finally:
        session.close()


def _item_with_keywords():
    session = SessionLocal()
    try:
        row = (
            session.query(Item.id)
            .filter(Item.ai_keywords.isnot(None), Item.ai_keywords != "")
            .first()
        )
        return row[0] if row else None
    finally:
        session.close()


# -- Keyword service -------------------------------------------------------


def test_split_deduplicates_and_trims():
    assert ks._split("  malaria , Malaria,  plants.  ,,") == ["malaria", "plants"]


def test_split_handles_empty():
    assert ks._split(None) == []
    assert ks._split("") == []
    assert ks._split(" , , ") == []


def test_keyword_coverage_shape():
    cov = ks.keyword_coverage()
    for field in (
        "total_items",
        "items_with_keywords",
        "coverage_pct",
        "special_collections_items",
        "special_collections_with_keywords",
    ):
        assert field in cov
    assert cov["items_with_keywords"] <= cov["total_items"]
    assert 0 <= cov["coverage_pct"] <= 100


def test_get_item_keywords_unknown_item():
    data = ks.get_item_keywords(99999999)
    assert data["source"] == "not_found"
    assert data["keywords"] == []


def test_get_item_keywords_returns_list():
    item_id = _item_with_keywords()
    if not item_id:
        pytest.skip("no item with stored keywords")
    data = ks.get_item_keywords(item_id)
    assert data["source"] in ("stored", "extracted")
    assert isinstance(data["keywords"], list)
    assert all(isinstance(k, str) and k for k in data["keywords"])


def test_search_by_keyword_empty_query_returns_nothing():
    assert ks.search_by_keyword("") == []
    assert ks.search_by_keyword("   ") == []


def test_search_by_keyword_marks_exact_matches():
    item_id = _item_with_keywords()
    if not item_id:
        pytest.skip("no item with stored keywords")
    kw = ks.get_item_keywords(item_id)["keywords"][0]
    results = ks.search_by_keyword(kw, limit=20)
    assert results, "the keyword's own record should match"
    assert any(r["exact_match"] for r in results)
    # Exact matches must sort ahead of substring-only ones.
    flags = [r["exact_match"] for r in results]
    assert flags == sorted(flags, reverse=True)


def test_related_by_keywords_excludes_self():
    item_id = _item_with_keywords()
    if not item_id:
        pytest.skip("no item with stored keywords")
    related = ks.related_by_keywords(item_id, limit=5)
    assert all(r["id"] != item_id for r in related)
    for r in related:
        assert 0 < r["overlap_score"] <= 1
        assert r["shared_keywords"]
    scores = [r["overlap_score"] for r in related]
    assert scores == sorted(scores, reverse=True)


def test_backfill_keywords_is_a_no_op_when_nothing_is_missing():
    stats = ks.backfill_keywords(limit=1)
    for field in ("scanned", "updated", "no_text", "skipped"):
        assert field in stats
    assert stats["updated"] <= stats["scanned"]


# -- Citation identity helpers ---------------------------------------------


def test_normalise_doi_strips_every_prefix_form():
    for raw in (
        "10.1234/ABC",
        "https://doi.org/10.1234/abc",
        "http://doi.org/10.1234/AbC",
        "doi:10.1234/abc",
        "  10.1234/abc  ",
    ):
        assert normalise_doi(raw) == "10.1234/abc"
    assert normalise_doi(None) == ""


def test_short_openalex_id_accepts_url_or_bare_id():
    assert short_openalex_id("https://openalex.org/W123") == "W123"
    assert short_openalex_id("W123") == "W123"
    assert short_openalex_id("") == ""


def test_edge_key_is_stable_and_directional():
    a = {"doi": "10.1/a"}
    b = {"doi": "10.1/b"}
    assert edge_key(a, b) == edge_key(a, b)
    assert edge_key(a, b) != edge_key(b, a)


def test_edge_key_collapses_doi_spelling_variants():
    assert edge_key({"doi": "https://doi.org/10.1/A"}, {"doi": "10.1/b"}) == edge_key(
        {"doi": "10.1/a"}, {"doi": "10.1/B"}
    )


def test_edge_key_falls_back_through_identity_types():
    # Same work described three ways must not collapse, but each form must be
    # stable on its own.
    by_doi = edge_key({"doi": "10.1/a"}, {"doi": "10.1/b"})
    by_oa = edge_key({"openalex_id": "W1"}, {"openalex_id": "W2"})
    by_title = edge_key({"title": "One"}, {"title": "Two"})
    assert len({by_doi, by_oa, by_title}) == 3
    assert edge_key({"title": "  One  "}, {"title": "two"}) == edge_key(
        {"title": "one"}, {"title": "TWO"}
    )


# -- Citation graph storage ------------------------------------------------


def test_citation_edges_do_not_require_both_ends_to_be_local():
    """The gap this service was built to close.

    The original implementation only wrote an edge when the citing work was
    already an Item, so an institution-scoped corpus recorded almost nothing.
    Both foreign keys are nullable now, and the external identity columns
    carry the edge on their own.
    """
    for column in (Citation.citing_item_id, Citation.cited_item_id):
        assert column.nullable, f"{column.key} must be nullable"
    for name in (
        "citing_doi",
        "citing_openalex_id",
        "citing_title",
        "citing_year",
        "cited_doi",
        "cited_openalex_id",
        "cited_title",
        "cited_year",
        "edge_key",
    ):
        assert hasattr(Citation, name), f"Citation.{name} missing"


def test_get_paper_citations_returns_both_directions():
    item_id = _any_item_id()
    if not item_id:
        pytest.skip("empty database")
    data = get_paper_citations(item_id)
    assert set(data) >= {
        "citation_count",
        "citing_papers",
        "references",
        "edges_stored",
    }
    assert isinstance(data["citing_papers"], list)
    assert isinstance(data["references"], list)
    for row in data["citing_papers"] + data["references"]:
        assert set(row) >= {"internal_id", "title", "doi", "openalex_id", "year"}


def test_citation_graph_coverage_shape():
    cov = get_citation_graph_coverage()
    for field in (
        "total_edges",
        "edges_between_two_local_records",
        "records_with_inbound_edges",
        "records_with_outbound_edges",
        "records_eligible_for_sync",
        "special_collections_eligible_for_sync",
    ):
        assert field in cov
        assert cov[field] >= 0
    assert cov["edges_between_two_local_records"] <= cov["total_edges"]


def test_sync_citation_graph_reports_missing_record_without_network():
    result = CitationTracker.sync_citation_graph(99999999)
    assert result["status"] == "not_found"
    assert result["new_edges"] == 0


def test_fetch_referenced_works_short_circuits_on_empty_input():
    # No ids means no request - guards against a backfill loop firing one
    # OpenAlex call per record that has no references.
    assert CitationTracker.fetch_referenced_works([]) == []
    assert CitationTracker.fetch_referenced_works([None, ""]) == []


def test_fetch_citing_works_short_circuits_without_an_id():
    assert CitationTracker.fetch_citing_works("") == []


# -- HTTP surface ----------------------------------------------------------


def test_keyword_endpoints_reachable(admin_client):
    assert admin_client.get("/api/keywords/coverage").status_code == 200
    r = admin_client.get("/api/keywords/search?q=health&limit=3")
    assert r.status_code == 200
    assert "results" in r.get_json()


def test_keyword_search_requires_a_query(admin_client):
    r = admin_client.get("/api/keywords/search")
    assert r.status_code == 400


def test_keyword_detail_404s_for_unknown_item(admin_client):
    assert admin_client.get("/api/keywords/99999999").status_code == 404


def test_citation_graph_endpoints_reachable(admin_client):
    assert admin_client.get("/api/citations/coverage").status_code == 200
    item_id = _any_item_id()
    if not item_id:
        pytest.skip("empty database")
    r = admin_client.get(f"/api/citations/{item_id}/graph?limit=5")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) >= {"item_id", "citing", "references", "edges_stored"}


def test_new_read_endpoints_are_partner_reachable():
    from uraas.dashboard.app import ADMIN_ENDPOINTS, PARTNER_ENDPOINTS

    for endpoint in (
        "keyword_cloud",
        "keyword_search",
        "keyword_coverage_stats",
        "item_keywords",
        "related_keywords",
        "get_citations",
        "citation_graph",
        "citation_coverage",
    ):
        assert endpoint in PARTNER_ENDPOINTS, f"{endpoint} not partner-readable"
        assert endpoint not in ADMIN_ENDPOINTS


def test_graph_sync_and_backfill_stay_admin_only():
    """These write and fan out to OpenAlex - a read-scoped partner key must
    never reach them."""
    from uraas.dashboard.app import ADMIN_ENDPOINTS, PARTNER_ENDPOINTS

    for endpoint in (
        "admin_backfill_keywords",
        "admin_sync_citation_graph",
        "admin_sync_citation_graphs",
    ):
        assert endpoint in ADMIN_ENDPOINTS
        assert endpoint not in PARTNER_ENDPOINTS


def test_admin_write_routes_reject_a_viewer_session(viewer_client):
    assert (
        viewer_client.post(
            "/api/admin/keywords/backfill", json={"limit": 1}
        ).status_code
        == 403
    )
    assert (
        viewer_client.post(
            "/api/admin/citations/sync-graph", json={"limit": 1}
        ).status_code
        == 403
    )
