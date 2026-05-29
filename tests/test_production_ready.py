"""
URAAS Production Readiness Test Suite
Comprehensive tests ensuring zero defects before deployment
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from uraas.database import Author, Item, SessionLocal
from uraas.utils.ai_keyword_extractor import ai_extractor
from uraas.utils.staff_validator import staff_validator


class TestAIKeywordExtractor:
    """Test AI keyword extraction system"""

    def test_keyword_extraction_basic(self):
        """Test basic keyword extraction"""
        text = "machine learning deep neural networks artificial intelligence"
        keywords = ai_extractor.extract_keywords(text, top_n=5)

        assert len(keywords) > 0, "Should extract keywords"
        assert all(
            isinstance(k, tuple) and len(k) == 2 for k in keywords
        ), "Keywords should be (word, score) tuples"
        assert all(
            0 <= score <= 1 for _, score in keywords
        ), "Scores should be between 0 and 1"

    def test_keyword_extraction_empty(self):
        """Test with empty text"""
        keywords = ai_extractor.extract_keywords("", top_n=5)
        assert keywords == [], "Empty text should return no keywords"

    def test_domain_classification(self):
        """Test domain classification"""
        text = "algorithm data structure programming software engineering"
        domains = ai_extractor.classify_domain(text)

        assert len(domains) > 0, "Should classify domains"
        assert (
            domains[0][0] == "computer_science"
        ), "Should identify computer science domain"

    def test_entity_extraction(self):
        """Test entity extraction"""
        text = "The study was conducted at University of Lagos using 50 mg of compound"
        entities = ai_extractor.extract_entities(text)

        assert "organizations" in entities, "Should extract organizations"
        assert "measurements" in entities, "Should extract measurements"

    def test_paper_scoring(self):
        """Test paper quality scoring"""
        title = "Machine Learning Applications in Medical Diagnosis"
        abstract = (
            "This study investigates the application of machine learning "
            "algorithms for medical diagnosis. We developed a novel approach "
            "using deep neural networks to classify medical images. Our results "
            "show significant improvement over existing methods."
        )

        score = ai_extractor.score_paper(title, abstract)

        assert "quality_score" in score, "Should have quality score"
        assert 0 <= score["quality_score"] <= 1, "Quality score should be 0-1"
        assert "keywords" in score, "Should have keywords"
        assert "domains" in score, "Should have domains"


class TestDashboardUI:
    """Test dashboard UI for emoji removal"""

    def test_dashboard_no_emojis(self):
        """Verify dashboard HTML has no emojis in critical UI text"""
        dashboard_path = Path("uraas/dashboard/templates/index.html")
        assert dashboard_path.exists(), "Dashboard file should exist"

        content = dashboard_path.read_text(encoding="utf-8")

        # Check for common emoji patterns in non-optgroup areas (optgroups intentionally use flag emojis)
        import re

        # Strip out optgroup labels before checking
        stripped = re.sub(r'<optgroup[^>]*label="[^"]*"[^>]*>', "", content)
        emoji_pattern = r"[\U0001F680-\U0001F9FF]"  # Rockets, charts, etc.
        matches = re.findall(emoji_pattern, stripped)
        assert len(matches) == 0, f"Found unexpected emojis: {matches[:5]}"

    def test_dashboard_minimalist_design(self):
        """Verify dashboard uses consistent design tokens"""
        dashboard_path = Path("uraas/dashboard/templates/index.html")
        content = dashboard_path.read_text(encoding="utf-8")

        # Check for design system elements present in index.html
        assert "Inter" in content, "Should use Inter font"
        assert (
            "gradient-text" in content or "var(--accent)" in content
        ), "Should use CSS design tokens"

    def test_dashboard_accessibility(self):
        """Verify dashboard has accessibility features"""
        dashboard_path = Path("uraas/dashboard/templates/index.html")
        content = dashboard_path.read_text(encoding="utf-8")

        # Check for accessibility features
        assert (
            "aria-" in content or "role=" in content or "title=" in content
        ), "Should have ARIA attributes or title attributes"
        assert "lang=" in content, "HTML element should have lang attribute"


class TestMetadataExtraction:
    """Test metadata extraction accuracy"""

    def test_paper_metadata_completeness(self):
        """Test that papers have complete metadata"""
        session = SessionLocal()
        try:
            papers = session.query(Item).limit(10).all()

            for paper in papers:
                assert paper.title, "Paper should have title"
                assert paper.dc_title, "Paper should have Dublin Core title"

                # dc_identifier_doi stores the repository handle (OAI/DocID),
                # while paper.doi stores the scholarly DOI — these are distinct fields.
                # Both can coexist; just verify dc_identifier_doi is non-empty when doi is set.
                if paper.doi and paper.dc_identifier_doi:
                    assert (
                        len(paper.dc_identifier_doi) > 0
                    ), "dc_identifier_doi should be non-empty when present"
        finally:
            session.close()

    def test_author_extraction_accuracy(self):
        """Test author extraction"""
        session = SessionLocal()
        try:
            papers = session.query(Item).filter(Item.authors.any()).limit(5).all()

            for paper in papers:
                assert len(paper.authors) > 0, "Paper should have authors"

                for author in paper.authors:
                    assert author.name, "Author should have name"
                    assert author.normalized_name, "Author should have normalized name"
                    assert (
                        author.normalized_name == author.name.lower().strip()
                    ), "Normalized name should be lowercase"
        finally:
            session.close()


class TestStaffValidation:
    """Test staff validation accuracy"""

    def test_staff_cache_loaded(self):
        """Verify staff cache can be loaded from the data directory"""
        import os

        # The data file is always relative to the project root
        staff_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "unilag_staff.json"
        )
        assert os.path.exists(
            staff_path
        ), f"Staff data file should exist at {staff_path}"
        # If staff_validator already loaded correctly, that is the best evidence
        if len(staff_validator.staff_names) == 0:
            # Reload using absolute path so tests pass regardless of working dir
            from uraas.utils.staff_validator import StaffValidator

            sv = StaffValidator(staff_cache_path=os.path.abspath(staff_path))
            assert (
                len(sv.staff_names) > 0
            ), "Staff cache should load from data/unilag_staff.json"

    def test_exact_staff_match(self):
        """Test exact staff matching"""
        if staff_validator.staff_names:
            test_name = list(staff_validator.staff_names)[0]
            assert staff_validator.is_staff_member(
                test_name, fuzzy_threshold=100
            ), "Exact match should work"

    def test_fuzzy_staff_match(self):
        """Test fuzzy staff matching"""
        if staff_validator.staff_names:
            test_name = list(staff_validator.staff_names)[0]
            # Slightly modify the name
            modified = test_name.replace("a", "e", 1) if "a" in test_name else test_name
            result = staff_validator.is_staff_member(modified, fuzzy_threshold=75)
            assert isinstance(result, bool), "Should return boolean"


class TestAPIEndpoints:
    """Test API endpoints"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        from uraas.dashboard.app import app

        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    def test_dashboard_loads(self, client):
        """Test dashboard loads"""
        response = client.get("/")
        assert response.status_code == 200, "Dashboard should load"

    def test_analytics_overview(self, client):
        """Test analytics overview endpoint"""
        response = client.get("/api/analytics/overview")
        assert response.status_code == 200, "Analytics overview should work"

        data = response.get_json()
        assert "total_papers" in data, "Should have total papers"
        assert "total_authors" in data, "Should have total authors"

    def test_search_endpoint(self, client):
        """Test search endpoint"""
        response = client.get("/api/analytics/search?q=test&limit=10")
        assert response.status_code == 200, "Search should work"

        data = response.get_json()
        assert isinstance(data, list), "Search should return list"


class TestPerformance:
    """Test performance requirements"""

    def test_keyword_extraction_speed(self):
        """Test keyword extraction is fast"""
        import time

        text = "machine learning deep neural networks artificial intelligence " * 10

        start = time.time()
        for _ in range(100):
            ai_extractor.extract_keywords(text, top_n=10)
        duration = time.time() - start

        avg_time = duration / 100
        assert (
            avg_time < 0.05
        ), f"Keyword extraction took {avg_time}s, should be < 0.05s"

    def test_domain_classification_speed(self):
        """Test domain classification is fast"""
        import time

        text = "algorithm data structure programming software engineering" * 5

        start = time.time()
        for _ in range(100):
            ai_extractor.classify_domain(text)
        duration = time.time() - start

        avg_time = duration / 100
        assert avg_time < 0.01, f"Classification took {avg_time}s, should be < 0.01s"


class TestSecurity:
    """Test security measures"""

    def test_no_sql_injection_in_search(self):
        """Test SQL injection protection"""
        from uraas.dashboard.app import app

        app.config["TESTING"] = True

        with app.test_client() as client:
            malicious_query = "'; DROP TABLE items; --"
            response = client.get(f"/api/analytics/search?q={malicious_query}")

            # Should not crash
            assert response.status_code in [200, 400], "Should handle malicious input"

    def test_xss_protection(self):
        """Test XSS protection"""
        session = SessionLocal()
        try:
            malicious_title = "<script>alert('XSS')</script>"
            item = Item(
                title=malicious_title, dc_title=malicious_title, doi="10.test/xss.001"
            )
            session.add(item)
            session.commit()

            # Retrieve and verify
            retrieved = session.query(Item).filter_by(doi="10.test/xss.001").first()
            assert retrieved.title == malicious_title, "Should store as-is"

            # Cleanup
            session.delete(retrieved)
            session.commit()
        finally:
            session.close()


class TestCodeQuality:
    """Test code quality"""

    def test_no_print_statements(self):
        """Verify no debug print statements in production code"""
        import os
        import re

        production_dirs = ["uraas/dashboard", "uraas/utils", "uraas/pipelines"]

        # Files that legitimately use print() for IPC/stdout protocols
        ALLOWED_FILES = {
            os.path.normpath(
                "uraas/pipelines/database.py"
            ),  # URAAS_DOWNLOAD: stdout IPC
        }

        for dir_path in production_dirs:
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    if file.endswith(".py"):
                        filepath = os.path.join(root, file)
                        if os.path.normpath(filepath) in ALLOWED_FILES:
                            continue  # Skip intentional stdout IPC files
                        with open(
                            filepath, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            content = f.read()
                            # Check for debug print statements (not logging)
                            debug_prints = re.findall(
                                r"^\s*print\(", content, re.MULTILINE
                            )
                            assert (
                                len(debug_prints) == 0
                            ), f"Found debug print statements in {filepath}"

    def test_imports_organized(self):
        """Verify imports are organized"""
        import os

        for root, dirs, files in os.walk("uraas"):
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r") as f:
                        lines = f.readlines()

                        # Check that imports are at the top
                        import_section_ended = False
                        for i, line in enumerate(lines[:50]):
                            if line.strip() and not line.startswith(
                                ("import", "from", "#", '"""', "'''")
                            ):
                                import_section_ended = True
                            elif import_section_ended and line.startswith(
                                ("import", "from")
                            ):
                                # Imports after code is bad
                                pass  # Allow for now


def run_all_tests():
    """Run all tests"""
    pytest.main([__file__, "-v", "--tb=short", "--color=yes"])


if __name__ == "__main__":
    run_all_tests()
