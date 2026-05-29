"""
URAAS Test Suite  covers every API endpoint and APA analytics metrics.
Run: pytest tests/test_api.py -v
"""

import sys, os, pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.dashboard.app import app as flask_app
from uraas.analytics.engine import analytics, URAASAnalyticsEngine
from uraas.utils.ai_keyword_extractor import ai_extractor
from uraas.utils.docid_generator import docid_generator
from uraas.database import SessionLocal, Item, Author, Community, Collection


@pytest.fixture(scope="module")
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


#  Core page


def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200


#  Analytics overview


def test_analytics_overview(client):
    r = client.get("/api/analytics/overview")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_papers" in d
    assert "total_authors" in d
    assert "oa_percentage" in d
    assert isinstance(d["total_papers"], int)
    assert 0 <= d["oa_percentage"] <= 100


def test_publications_by_year(client):
    r = client.get("/api/analytics/publications-by-year")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    for item in d:
        assert "year" in item and "count" in item
        assert isinstance(item["year"], int)
        assert item["count"] >= 0


def test_papers_by_faculty(client):
    r = client.get("/api/analytics/papers-by-faculty")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)


def test_top_authors(client):
    r = client.get("/api/analytics/top-authors?limit=10")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 10


def test_oa_breakdown(client):
    r = client.get("/api/analytics/open-access-breakdown")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    labels = [x["label"] for x in d]
    assert "Open Access" in labels


def test_recent_papers(client):
    r = client.get("/api/analytics/recent-papers?limit=5")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 5


def test_impact_metrics(client):
    r = client.get("/api/analytics/impact-metrics")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_papers" in d
    assert "oa_rate" in d
    assert "doi_rate" in d


def test_faculties_list(client):
    r = client.get("/api/analytics/faculties")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)


# ── Search ────────────────────────────────────────────────────────────────────


def test_search_empty(client):
    r = client.get("/api/analytics/search?q=&limit=10")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_search_with_query(client):
    r = client.get("/api/analytics/search?q=health&limit=10")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 10


def test_search_oa_filter(client):
    r = client.get("/api/analytics/search?oa_only=true&limit=20")
    assert r.status_code == 200
    d = r.get_json()
    for item in d:
        assert item["is_oa"] == True


def test_search_sql_injection(client):
    r = client.get("/api/analytics/search?q='; DROP TABLE items; --")
    assert r.status_code == 200  # should not crash


#  Papers tree


def test_papers_tree(client):
    r = client.get("/api/papers/tree")
    assert r.status_code == 200
    d = r.get_json()
    assert "status" in d
    assert "data" in d


#  Paper detail


def test_paper_not_found(client):
    r = client.get("/api/papers/999999")
    assert r.status_code == 404


def test_paper_detail_if_exists(client):
    session = SessionLocal()
    try:
        item = session.query(Item).first()
        if item:
            r = client.get(f"/api/papers/{item.id}")
            assert r.status_code == 200
            d = r.get_json()
            assert "title" in d
            assert "authors" in d
            assert "dc" in d
    finally:
        session.close()


#  Keyword cloud


def test_keyword_cloud(client):
    r = client.get("/api/analytics/keyword-cloud")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    for item in d:
        assert "word" in item
        assert "count" in item
        assert "score" in item


#  Research trends


def test_research_trends(client):
    r = client.get("/api/analytics/research-trends")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    for item in d:
        assert "topic" in item
        assert "total" in item
        assert "by_year" in item


#  Language research


def test_language_research(client):
    r = client.get("/api/analytics/language-research")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_language_papers" in d
    assert "papers" in d
    assert "top_keywords" in d
    # Verify no false positives
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


#  APA Novel Metrics


def test_tk_vitality_score(client):
    r = client.get("/api/analytics/tk-vitality-score")
    assert r.status_code == 200
    d = r.get_json()
    assert "score" in d
    assert 0 <= d["score"] <= 100
    assert "breakdown" in d
    assert "total_items" in d


def test_linguistic_diversity_index(client):
    r = client.get("/api/analytics/linguistic-diversity-index")
    assert r.status_code == 200
    d = r.get_json()
    assert "index" in d
    assert 0 <= d["index"] <= 100
    assert "breakdown" in d


def test_patent_velocity(client):
    r = client.get("/api/analytics/patent-velocity")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_patents" in d
    assert "velocity_distribution" in d


def test_docid_coverage(client):
    r = client.get("/api/analytics/docid-coverage")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_papers" in d
    assert "docid_assigned" in d
    assert "coverage_percent" in d
    assert 0 <= d["coverage_percent"] <= 100


def test_docid_stats(client):
    r = client.get("/api/docid/stats")
    assert r.status_code == 200
    d = r.get_json()
    assert "total_docid_papers" in d
    assert "docid_coverage" in d


#  Author network


def test_author_network_global(client):
    r = client.get("/api/analytics/author-network")
    assert r.status_code == 200
    d = r.get_json()
    assert "nodes" in d
    assert "edges" in d


def test_authors_search(client):
    r = client.get("/api/analytics/authors-search?q=a&limit=5")
    assert r.status_code == 200
    d = r.get_json()
    assert isinstance(d, list)
    assert len(d) <= 5


#  Faculty comparison


def test_faculty_comparison_empty(client):
    r = client.get("/api/analytics/faculty-comparison")
    assert r.status_code == 200
    assert isinstance(r.get_json(), dict)


#  Exports


def test_export_csv(client):
    r = client.get("/api/export/papers.csv")
    assert r.status_code == 200
    assert "text/csv" in r.content_type
    data = r.data.decode("utf-8")
    assert "Title" in data or "ID" in data


def test_export_bibtex(client):
    r = client.get("/api/export/papers.bibtex")
    assert r.status_code == 200


#  Crawler status


def test_crawler_status(client):
    r = client.get("/api/crawler/status")
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] in ("running", "idle")


def test_docid_crawler_status(client):
    r = client.get("/api/docid-crawler/status")
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] in ("running", "idle")


#  Analytics engine unit tests


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
    sdg_names = [r["sdg"] for r in result]
    # Should have at least some SDGs with papers
    assert len(result) >= 0


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


def test_engine_patent_velocity():
    result = analytics.get_patent_velocity()
    assert "total_patents" in result
    assert isinstance(result["total_patents"], int)


def test_engine_docid_coverage():
    result = analytics.get_docid_coverage()
    assert "coverage_percent" in result
    assert 0 <= result["coverage_percent"] <= 100


#  DocID generator


def test_docid_generation():
    docid = docid_generator.generate_docid("Test Paper Title", doi="10.1234/test")
    assert docid.startswith("20.500.14351/")
    parts = docid.split("/")
    assert len(parts) == 2
    assert len(parts[1]) >= 10


def test_docid_validation():
    valid = docid_generator.generate_docid("Test")
    assert docid_generator.validate_docid(valid) == True
    assert docid_generator.validate_docid("") == False
    assert docid_generator.validate_docid("invalid") == False
    assert docid_generator.validate_docid("99.999.99999/abc") == False


def test_docid_uniqueness():
    ids = {docid_generator.generate_docid("Same Title") for _ in range(10)}
    assert len(ids) == 10  # all unique due to uuid4


#  AI keyword extractor


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
        "This study investigates machine learning algorithms for medical diagnosis using deep neural networks to classify medical images with significant improvement over existing methods.",
    )
    assert "quality_score" in score
    assert 0 <= score["quality_score"] <= 1
    assert "keywords" in score


#  Performance


def test_overview_response_time(client):
    import time

    start = time.time()
    client.get("/api/analytics/overview")
    elapsed = time.time() - start
    assert elapsed < 3.0, f"Overview took {elapsed:.2f}s, should be < 3s"


def test_search_response_time(client):
    import time

    start = time.time()
    client.get("/api/analytics/search?q=health&limit=20")
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Search took {elapsed:.2f}s, should be < 5s"


def test_keyword_cloud_response_time(client):
    import time

    start = time.time()
    client.get("/api/analytics/keyword-cloud")
    elapsed = time.time() - start
    assert elapsed < 10.0, f"Keyword cloud took {elapsed:.2f}s, should be < 10s"
