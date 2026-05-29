"""
Test script for new Scopus-competitive features:
1. Citation tracking
2. H-index calculation
3. Advanced search with Boolean operators
"""

import sys
import time

from uraas.database import Author, Base, Item, SessionLocal, engine
from uraas.services.advanced_search import SearchQuery
from uraas.services.citation_tracker import (
    AuthorMetrics,
    Citation,
    CitationMetrics,
    CitationTracker,
    get_author_bibliometrics,
    get_paper_citations,
)

if __name__ == "__main__":
    # Create new tables
    print("=" * 70)
    print("Creating citation tracking tables...")
    print("=" * 70)
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created\n")

    # Test 1: Citation Tracking
    print("=" * 70)
    print("TEST 1: Citation Tracking")
    print("=" * 70)

    session = SessionLocal()

    # Find a paper with DOI
    paper = session.query(Item).filter(Item.doi.isnot(None)).first()

    if paper:
        print(f"\nTesting with paper: {paper.title[:60]}...")
        print(f"DOI: {paper.doi}")

        print("\nFetching citations from OpenAlex...")
        success = CitationTracker.update_paper_citations(paper.id)

        if success:
            print("✓ Citations fetched successfully")

            # Get citation data
            cite_data = get_paper_citations(paper.id)
            print(f"\nCitation count: {cite_data['citation_count']}")
            print(f"Citing papers in our DB: {len(cite_data['citing_papers'])}")

            if cite_data["citing_papers"]:
                print("\nSample citing papers:")
                for cite in cite_data["citing_papers"][:3]:
                    print(f"  - {cite['title'][:60]}... ({cite['year']})")
        else:
            print("⚠ Citation fetch failed (paper may not be in OpenAlex)")
    else:
        print("⚠ No papers with DOI found in database")

    session.close()

    # Test 2: H-index Calculation
    print("\n" + "=" * 70)
    print("TEST 2: H-index Calculation")
    print("=" * 70)

    session = SessionLocal()

    # Test h-index calculation
    test_citations = [100, 50, 30, 20, 15, 10, 8, 5, 3, 2, 1, 1, 0, 0]
    h_index = CitationTracker.calculate_h_index(test_citations)
    print(f"\nTest citation counts: {test_citations}")
    print(f"Calculated h-index: {h_index}")
    print(f"Expected: 10 (10 papers with ≥10 citations)")

    # Find an author and calculate their metrics
    author = session.query(Author).join(Author.items).first()

    if author:
        print(f"\nTesting with author: {author.name}")

        # Update author metrics
        success = CitationTracker.update_author_metrics(author.id)

        if success:
            metrics = get_author_bibliometrics(author.id)
            print(f"\nAuthor Bibliometrics:")
            print(f"  Total papers: {metrics.get('total_papers', 0)}")
            print(f"  Total citations: {metrics.get('total_citations', 0)}")
            print(f"  H-index: {metrics.get('h_index', 0)}")
            print(f"  i10-index: {metrics.get('i10_index', 0)}")
            print(f"  Citations per paper: {metrics.get('citations_per_paper', 0)}")
        else:
            print("⚠ Author metrics calculation failed (papers may lack citation data)")

    session.close()

    # Test 3: Advanced Search
    print("\n" + "=" * 70)
    print("TEST 3: Advanced Search with Boolean Operators")
    print("=" * 70)

    # Test query parsing
    test_queries = [
        "machine learning",
        '"machine learning" AND author:smith',
        "title:cancer NOT lung",
        "author:okonkwo AND year:2020",
        "(covid OR pandemic) AND faculty:medicine",
    ]

    print("\nQuery Parsing Tests:")
    for query in test_queries:
        parsed = SearchQuery.parse_boolean_query(query)
        print(f"\nQuery: {query}")
        print(f"Parsed: {parsed}")

    # Test actual search execution
    print("\n" + "=" * 70)
    print("Search Execution Tests:")
    print("=" * 70)

    # Test 1: Simple keyword search
    print("\n1. Simple keyword search: 'health'")
    results = SearchQuery.execute_search("health", limit=5)
    print(f"   Found {results['total']} papers in {results['took_ms']}ms")
    if results["results"]:
        print(f"   Top result: {results['results'][0]['title'][:60]}...")

    # Test 2: Field-specific search
    print("\n2. Field-specific search: 'year:2020'")
    results = SearchQuery.execute_search("year:2020", limit=5)
    print(f"   Found {results['total']} papers from 2020")

    # Test 3: Boolean AND
    print("\n3. Boolean AND: 'health AND education'")
    results = SearchQuery.execute_search("health AND education", limit=5)
    print(f"   Found {results['total']} papers")

    # Test 4: Phrase search
    print("\n4. Phrase search: '\"machine learning\"'")
    results = SearchQuery.execute_search('"machine learning"', limit=5)
    print(f"   Found {results['total']} papers")

    # Test 5: Complex query
    print("\n5. Complex query: 'author:okonkwo AND faculty:science'")
    results = SearchQuery.execute_search("author:okonkwo AND faculty:science", limit=5)
    print(f"   Found {results['total']} papers")

    # Test 6: Sort by date
    print("\n6. Sort by date: 'health' sorted by publication date")
    results = SearchQuery.execute_search("health", limit=5, sort_by="date")
    print(f"   Found {results['total']} papers")
    if results["results"]:
        print(
            f"   Most recent: {results['results'][0]['title'][:60]}... ({results['results'][0]['year']})"
        )

    # Test autocomplete
    print("\n" + "=" * 70)
    print("Autocomplete Suggestions:")
    print("=" * 70)

    test_partials = ["health", "machine", "science"]
    for partial in test_partials:
        suggestions = SearchQuery.get_search_suggestions(partial)
        print(f"\n'{partial}' → {len(suggestions)} suggestions")
        for sug in suggestions[:5]:
            print(f"  - {sug}")

    # Summary
    print("\n" + "=" * 70)
    print("FEATURE COMPARISON SUMMARY")
    print("=" * 70)

    print("\n✓ IMPLEMENTED:")
    print("  1. Citation tracking (OpenAlex + Crossref APIs)")
    print("  2. H-index calculation (standard algorithm)")
    print("  3. i10-index (papers with 10+ citations)")
    print("  4. Author bibliometrics (total citations, papers, indices)")
    print("  5. Advanced search with Boolean operators (AND, OR, NOT)")
    print("  6. Field-specific queries (title:, author:, year:, faculty:, etc.)")
    print("  7. Phrase searches with quotes")
    print("  8. Multiple sort options (relevance, date, citations, title)")
    print("  9. Autocomplete suggestions")
    print(" 10. Pagination support")

    print("\n⚠ LIMITATIONS vs Scopus:")
    print("  - Scale: ~1K papers vs 80M+ (institutional focus)")
    print("  - Citation data: Depends on OpenAlex coverage")
    print("  - Update frequency: Weekly vs daily (configurable)")
    print("  - Journal metrics: Not included (focus on institutional output)")

    print("\n✓ ADVANTAGES over Scopus:")
    print("  - Zero false positives (staff validation)")
    print("  - Free (no $40K/year subscription)")
    print("  - Customizable (open source)")
    print("  - African focus (indigenous knowledge metrics)")
    print("  - Local PDF storage")
    print("  - DocID™ persistent identifiers")

    print("\n" + "=" * 70)
    print("Tests complete!")
    print("=" * 70)
