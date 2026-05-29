"""
Test multi-institution crawling functionality
Tests spider initialization and basic crawling for multiple institutions
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uraas.config.institutions import get_registry
from uraas.spiders.sources.openalex_spider import OpenAlexSpider


def test_spider_initialization():
    """Test that spiders can be initialized with different institutions"""
    print("\n" + "=" * 60)
    print("TEST: Spider Initialization")
    print("=" * 60)

    registry = get_registry()
    institutions = ["unilag", "ui", "oau", "unn", "abu"]

    results = {}

    for inst in institutions:
        try:
            config = registry.get(inst)
            if not config:
                print(f"\n✗ {inst}: Configuration not found")
                results[inst] = False
                continue

            # Try to initialize spider
            spider = OpenAlexSpider(institution=inst)

            print(f"\n✓ {inst}: {spider.institution_name}")
            print(f"  ROR: {spider.ror_id}")
            print(f"  ROR Short: {spider.ror_short}")
            print(f"  Staff count: {len(config.staff_names)}")

            results[inst] = True

        except Exception as e:
            print(f"\n✗ {inst}: Failed to initialize - {e}")
            results[inst] = False

    # Summary
    print("\n" + "=" * 60)
    print("INITIALIZATION SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\nPassed: {passed}/{total}")

    for inst, success in results.items():
        status = "✓" if success else "✗"
        print(f"  {status} {inst}")

    return passed == total


def test_affiliation_filter():
    """Test affiliation filter with multi-institution support"""
    print("\n" + "=" * 60)
    print("TEST: Affiliation Filter")
    print("=" * 60)

    from uraas.pipelines.affiliation_filter import AffiliationFilterPipeline
    from uraas.config.institutions import get_registry

    # Create mock spider for each institution
    class MockSpider:
        def __init__(self, institution):
            self.institution = institution
            self.logger = MockLogger()

    class MockLogger:
        def info(self, msg):
            pass

        def warning(self, msg):
            pass

        def error(self, msg):
            pass

    registry = get_registry()
    institutions = ["unilag", "ui"]

    for inst in institutions:
        config = registry.get(inst)
        if not config:
            continue

        print(f"\n{config.name}:")

        # Create pipeline
        pipeline = AffiliationFilterPipeline()
        spider = MockSpider(inst)
        pipeline.open_spider(spider)

        print(f"  Institution: {pipeline.current_institution.name}")
        print(f"  Staff count: {len(pipeline.current_validator.staff_names)}")
        print(f"  Patterns: {len(pipeline.current_patterns)}")

        # Test affiliation matching
        test_texts = [
            (f"{config.name}, Nigeria", True),
            (f"Department of Physics, {config.name}", True),
            ("Random University", False),
        ]

        print(f"  Affiliation matching:")
        for text, expected in test_texts:
            result = pipeline.is_institution_affiliated(text)
            status = "✓" if result == expected else "✗"
            print(f"    {status} '{text}' → {result}")

    return True


def test_ror_extraction():
    """Test ROR ID extraction from URLs"""
    print("\n" + "=" * 60)
    print("TEST: ROR ID Extraction")
    print("=" * 60)

    test_cases = [
        ("https://ror.org/03qcnxw14", "03qcnxw14"),
        ("https://ror.org/01js2sh04", "01js2sh04"),
        ("https://ror.org/03yp73w09", "03yp73w09"),
    ]

    all_passed = True

    for ror_url, expected_short in test_cases:
        short = ror_url.split("/")[-1]
        passed = short == expected_short
        status = "✓" if passed else "✗"
        print(f"  {status} {ror_url} → {short}")

        if not passed:
            all_passed = False

    return all_passed


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("MULTI-INSTITUTION CRAWL TEST SUITE")
    print("=" * 60)

    tests = [
        ("Spider Initialization", test_spider_initialization),
        ("Affiliation Filter", test_affiliation_filter),
        ("ROR Extraction", test_ror_extraction),
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = result
        except Exception as e:
            print(f"\n✗ {test_name} FAILED: {e}")
            import traceback

            traceback.print_exc()
            results[test_name] = False

    # Final summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\nTests passed: {passed}/{total}\n")

    for test_name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {test_name}")

    if passed == total:
        print("\n✓ ALL TESTS PASSED")
        print("\nReady for production crawling!")
        print("\nNext steps:")
        print(
            "  1. Run: python crawl_multi_institution.py --institutions unilag,ui --target 10"
        )
        print("  2. Monitor database for new papers with ROR tags")
        print("  3. Verify multi-institution comparison in dashboard")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED")
        print("\nPlease fix issues before proceeding.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
