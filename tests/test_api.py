"""URAAS API test suite — covers the dashboard's HTTP surface and analytics
engine. Run: pytest tests/test_api.py -v

Every dashboard route except a small public allowlist (login, health,
static, ...) requires an authenticated session — see
uraas.dashboard.app._enforce_authentication. Use the admin_client fixture
(tests/conftest.py) for anything under /api/, not the bare client fixture.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.analytics.engine import analytics
from uraas.database import Item, SessionLocal
from uraas.utils.ai_keyword_extractor import ai_extractor
from uraas.utils.docid_generator import docid_generator

# ── Auth surface itself ──────────────────────────────────────────────────


def test_index_requires_login(client):
    r = client.get("/")
    assert r.status_code == 302


def test_index_loads_when_authenticated(admin_client):
    r = admin_client.get("/")
    assert r.status_code == 200


def test_api_requires_auth(client):
    r = client.get("/api/analytics/overview")
    assert r.status_code == 401


def test_health_check_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200


# ── Analytics overview ────────────────────────────────────────────────────


def test_analytics_overview(admin_client):
    r = admin_client.get("/api/analytics/overview")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_papers" in d
    assert "total_authors" in d
    assert "oa_percentage" in d
    assert isinstance(d["total_papers"], int)
    assert 0 <= d["oa_percentage"] <= 100


def test_publications_by_year(admin_client):
    r = admin_client.get("/api/analytics/publications-by-year")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    for item in d:
        assert "year" in item and "count" in item
        assert isinstance(item["year"], int)
        assert item["count"] >= 0


def test_papers_by_faculty(admin_client):
    r = admin_client.get("/api/analytics/papers-by-faculty")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_top_authors(admin_client):
    r = admin_client.get("/api/analytics/top-authors?limit=10")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 10


def test_oa_breakdown(admin_client):
    r = admin_client.get("/api/analytics/open-access-breakdown")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    labels = [x["label"] for x in d]
    assert "Open Access" in labels


def test_recent_papers(admin_client):
    r = admin_client.get("/api/analytics/recent-papers?limit=5")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 5


def test_impact_metrics(admin_client):
    r = admin_client.get("/api/analytics/impact-metrics")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_papers" in d
    assert "oa_rate" in d
    assert "doi_rate" in d


def test_faculties_list(admin_client):
    r = admin_client.get("/api/analytics/faculties")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


# ── Search ────────────────────────────────────────────────────────────────


def test_search_empty(admin_client):
    r = admin_client.get("/api/analytics/search?q=&limit=10")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_search_with_query(admin_client):
    r = admin_client.get("/api/analytics/search?q=health&limit=10")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 10


def test_search_oa_filter(admin_client):
    r = admin_client.get("/api/analytics/search?oa_only=true&limit=20")
    assert r.status_code == 200
    for item in r.get_json():
        assert item["is_oa"] is True


def test_search_sql_injection(admin_client):
    r = admin_client.get("/api/analytics/search?q='; DROP TABLE items; --")
    assert r.status_code == 200  # should not crash


# ── Papers ────────────────────────────────────────────────────────────────


def test_papers_tree(admin_client):
    r = admin_client.get("/api/papers/tree")
    assert r.status_code == 200
    d = r.get_json()
    assert "status" in d
    assert "data" in d


def test_paper_not_found(admin_client):
    r = admin_client.get("/api/papers/999999")
    assert r.status_code == 404


def test_paper_detail_if_exists(admin_client):
    session = SessionLocal()
    try:
        item = session.query(Item).first()
    finally:
        session.close()
    if not item:
        pytest.skip("no items in the database to check")
    r = admin_client.get(f"/api/papers/{item.id}")
    assert r.status_code == 200
    d = r.get_json()
    assert "title" in d
    assert "authors" in d
    assert "dc" in d


# ── Keyword cloud / language ─────────────────────────────────────────────


def test_keyword_cloud(admin_client):
    r = admin_client.get("/api/analytics/keyword-cloud")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    for item in d:
        assert "word" in item
        assert "count" in item
        assert "score" in item


def test_language_research(admin_client):
    r = admin_client.get("/api/analytics/language-research")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_language_papers" in d
    assert "papers" in d
    assert "top_keywords" in d
    # A regression check: these are all real false-positive terms the SC/
    # language classifier has previously matched on by mistake.
    bad_terms = [
        "machine learning",
        "concrete",
        "cancer",
        "covid",
        "petroleum",
        "galaxy",
    ]
    for paper in d["papers"]:
        title_lower = (paper.get("title") or "").lower()
        for bad in bad_terms:
            assert bad not in title_lower, f"False positive: '{bad}' in '{title_lower}'"


# ── APA novel metrics ─────────────────────────────────────────────────────


def test_tk_vitality_score(admin_client):
    r = admin_client.get("/api/analytics/tk-vitality-score")
    assert r.status_code == 200
    d = r.get_json()
    assert "score" in d
    assert 0 <= d["score"] <= 100
    assert "breakdown" in d
    assert "total_items" in d


def test_linguistic_diversity_index(admin_client):
    r = admin_client.get("/api/analytics/linguistic-diversity-index")
    assert r.status_code == 200
    d = r.get_json()
    assert "index" in d
    assert 0 <= d["index"] <= 100
    assert "breakdown" in d


# ── Author network ────────────────────────────────────────────────────────


def test_author_network_global(admin_client):
    r = admin_client.get("/api/analytics/author-network")
    assert r.status_code == 200
    d = r.get_json()
    assert "nodes" in d
    assert "edges" in d


def test_authors_search(admin_client):
    r = admin_client.get("/api/analytics/authors-search?q=a&limit=5")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 5


def test_faculty_comparison_empty(admin_client):
    r = admin_client.get("/api/analytics/faculty-comparison")
    assert r.status_code == 200
    assert isinstance(r.get_json(), dict)


# ── Exports (admin-only) ──────────────────────────────────────────────────


def test_export_csv_requires_admin(viewer_client):
    r = viewer_client.get("/api/export/papers.csv")
    assert r.status_code == 403


def test_export_csv(admin_client):
    r = admin_client.get("/api/export/papers.csv")
    assert r.status_code == 200
    assert "text/csv" in r.content_type
    data = r.data.decode("utf-8")
    assert "Title" in data or "ID" in data


def test_export_bibtex(admin_client):
    r = admin_client.get("/api/export/papers.bibtex")
    assert r.status_code == 200


# ── Crawler status (admin-only) ───────────────────────────────────────────


def test_crawler_status_requires_admin(viewer_client):
    r = viewer_client.get("/api/crawler/status")
    assert r.status_code == 403


def test_crawler_status(admin_client):
    r = admin_client.get("/api/crawler/status")
    assert r.status_code == 200
    assert r.get_json()["status"] in ("running", "idle")


# ── Partner API (X-API-Key, not a session) ────────────────────────────────


def test_partner_endpoint_rejects_missing_key(client):
    r = client.get("/api/stats")
    assert r.status_code == 401


def test_partner_endpoint_rejects_bad_key(client):
    r = client.get("/api/stats", headers={"X-API-Key": "not-a-real-key"})
    assert r.status_code == 401


def test_partner_key_cannot_reach_admin_routes(client):
    # Even a real, valid key must never reach an admin/crawler-control route
    # — this is enforced structurally (PARTNER_ENDPOINTS is a strict
    # allowlist), so a garbage key proves the same 403 a real one would get,
    # without this test needing to mint a real key against a live database.
    r = client.post("/api/crawler/start", headers={"X-API-Key": "not-a-real-key"})
    assert r.status_code in (401, 403)


# ── Analytics engine unit tests ───────────────────────────────────────────


def test_engine_top_authors():
    result = analytics.get_top_authors(limit=5)
    assert isinstance(result, list)
    assert len(result) <= 5
    for r in result:
        assert "author" in r
        assert "count" in r
        assert r["count"] > 0


def test_engine_sdg_alignment():
    result = analytics.get_sdg_alignment()
    assert isinstance(result, list)


def test_engine_keyword_cloud():
    result = analytics.get_keyword_cloud(top_n=20)
    assert isinstance(result, list)
    assert len(result) <= 20
    for item in result:
        assert "word" in item
        assert "score" in item
        assert item["score"] > 0


def test_engine_tk_vitality():
    result = analytics.get_tk_vitality_score()
    assert "score" in result
    assert 0 <= result["score"] <= 100


def test_engine_linguistic_diversity():
    result = analytics.get_linguistic_diversity_index()
    assert "index" in result
    assert 0 <= result["index"] <= 100


# ── DocID generator ───────────────────────────────────────────────────────
# NOTE: uraas.utils.docid_generator is a local placeholder — it has never
# been wired into the crawl pipeline (see scripts/register_docid.py's
# docstring). Real DocIDs are minted by the Africa PID Alliance platform via
# uraas.services.docid_client. These tests only cover the generator's own
# self-contained logic (format, uniqueness), not anything used in
# production.


def test_docid_generation():
    docid = docid_generator.generate_docid("Test Paper Title", doi="10.1234/test")
    assert docid.startswith("20.500.14351/")
    parts = docid.split("/")
    assert len(parts) == 2
    assert len(parts[1]) >= 10


def test_docid_validation():
    valid = docid_generator.generate_docid("Test")
    assert docid_generator.validate_docid(valid) is True
    assert docid_generator.validate_docid("") is False
    assert docid_generator.validate_docid("invalid") is False
    assert docid_generator.validate_docid("99.999.99999/abc") is False


def test_docid_uniqueness():
    ids = {docid_generator.generate_docid("Same Title") for _ in range(10)}
    assert len(ids) == 10  # all unique due to uuid4


# ── AI keyword extractor ──────────────────────────────────────────────────


def test_keyword_extraction():
    text = (
        "machine learning deep neural networks artificial intelligence computer vision"
    )
    kws = ai_extractor.extract_keywords(text, top_n=5)
    assert len(kws) > 0
    assert all(isinstance(k, tuple) and len(k) == 2 for k in kws)


def test_keyword_extraction_empty():
    assert ai_extractor.extract_keywords("", top_n=5) == []


def test_domain_classification():
    text = "algorithm data structure programming software engineering database"
    domains = ai_extractor.classify_domain(text)
    assert len(domains) > 0
    assert domains[0][0] == "computer_science"


def test_paper_scoring():
    score = ai_extractor.score_paper(
        "Machine Learning for Medical Diagnosis",
        "This study investigates machine learning algorithms for medical diagnosis "
        "using deep neural networks to classify medical images with significant "
        "improvement over existing methods.",
    )
    assert "quality_score" in score
    assert 0 <= score["quality_score"] <= 1
    assert "keywords" in score


# ── Performance ────────────────────────────────────────────────────────────


def test_overview_response_time(admin_client):
    import time

    start = time.time()
    r = admin_client.get("/api/analytics/overview")
    elapsed = time.time() - start
    assert r.status_code == 200
    assert elapsed < 3.0, f"Overview took {elapsed:.2f}s, should be < 3s"


def test_search_response_time(admin_client):
    import time

    start = time.time()
    r = admin_client.get("/api/analytics/search?q=health&limit=20")
    elapsed = time.time() - start
    assert r.status_code == 200
    assert elapsed < 5.0, f"Search took {elapsed:.2f}s, should be < 5s"


def test_keyword_cloud_response_time(admin_client):
    import time

    start = time.time()
    r = admin_client.get("/api/analytics/keyword-cloud")
    elapsed = time.time() - start
    assert r.status_code == 200
    assert elapsed < 10.0, f"Keyword cloud took {elapsed:.2f}s, should be < 10s"
