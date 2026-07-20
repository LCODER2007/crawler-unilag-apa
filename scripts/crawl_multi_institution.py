"""
Multi-Institution Crawler
Crawls papers for multiple Nigerian universities simultaneously
"""

import argparse
import os
import subprocess
import sys

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

# Force unbuffered output so terminal log is in correct order
sys.stdout.reconfigure(line_buffering=True)

# Add project root to path (parent of scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config.institutions import get_registry


def main():
    parser = argparse.ArgumentParser(
        description="Multi-institution research paper crawler"
    )
    parser.add_argument(
        "--institutions",
        type=str,
        default="all",
        help='Comma-separated list of institution short names, or "all" (default: all)',
    )
    parser.add_argument(
        "--target", type=int, default=20, help="Target number of papers per institution"
    )
    parser.add_argument(
        "--spider",
        type=str,
        default="openalex",
        choices=["openalex", "crossref", "arxiv", "orcid", "oai",
                 "semantic_scholar", "europepmc", "core", "pubmed",
                 "openaire", "doaj", "ajol", "datacite", "isni", "all"],
        help=(
            "Spider to use for crawling. "
            "'all' fans out across every web source (openalex + crossref + "
            "semantic_scholar + europepmc + arxiv + orcid) for maximum coverage."
        ),
    )
    parser.add_argument(
        "--from-date",
        dest="from_date",
        type=str,
        default=None,
        help="OAI harvest lower bound YYYY-MM-DD (oai spider only; "
        "defaults to a recent look-back window)",
    )
    parser.add_argument(
        "--until-date",
        dest="until_date",
        type=str,
        default=None,
        help="OAI harvest upper bound YYYY-MM-DD (oai spider only; optional)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run database cleanup script before crawling",
    )
    parser.add_argument(
        "--no-boost-special",
        dest="boost_special",
        action="store_false",
        help="Disable Special Collections boost waves (default: boost ON)",
    )
    parser.add_argument(
        "--sc-only",
        action="store_true",
        help="Crawl ONLY Special Collections seed waves (skip generic ROR pass)",
    )
    parser.set_defaults(boost_special=True)

    args = parser.parse_args()

    if args.clean:
        print("\n" + "=" * 60)
        print("RUNNING DATABASE CLEANUP")
        print("=" * 60)
        try:
            subprocess.run([sys.executable, "scripts/clean_database.py"], check=True)
            print("Cleanup completed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Cleanup failed: {e}")
            return 1

    registry = get_registry()

    if args.institutions.lower() == "all":
        valid_institutions = [inst.short_name.lower() for inst in registry.list_all()]
    else:
        # Parse institutions
        institution_list = [inst.strip() for inst in args.institutions.split(",")]
        valid_institutions = []
        for inst in institution_list:
            config = registry.get(inst)
            if config:
                valid_institutions.append(config.short_name.lower())
            else:
                print(f"  [NOT FOUND] '{inst}' not found in registry")

    print("\n" + "=" * 60, flush=True)
    print("MULTI-INSTITUTION CRAWLER", flush=True)
    print("=" * 60, flush=True)
    print(f"\nTarget: {args.target} papers total per institution", flush=True)
    print(f"Spider: {args.spider}", flush=True)
    print(f"\nValidating institutions...", flush=True)

    # Map spider names to classes (defined early so we can validate)
    spider_map = {
        "openalex":        "uraas.spiders.sources.openalex_spider.OpenAlexSpider",
        "crossref":        "uraas.spiders.sources.crossref_spider.CrossrefSpider",
        "arxiv":           "uraas.spiders.sources.arxiv_spider.ArxivSpider",
        "orcid":           "uraas.spiders.sources.orcid_spider.ORCIDSpider",
        "oai":             "uraas.spiders.sources.oai_spider.OAISpider",
        "semantic_scholar":"uraas.spiders.sources.semantic_scholar_spider.SemanticScholarSpider",
        "europepmc":       "uraas.spiders.sources.europepmc_spider.EuropePMCSpider",
        "core":            "uraas.spiders.sources.core_spider.CORESpider",
        "pubmed":          "uraas.spiders.sources.pubmed_spider.PubMedSpider",
        "openaire":        "uraas.spiders.sources.openaire_spider.OpenAIRESpider",
        "doaj":            "uraas.spiders.sources.doaj_spider.DOAJSpider",
        "ajol":            "uraas.spiders.sources.ajol_spider.AJOLSpider",
        "datacite":        "uraas.spiders.sources.datacite_spider.DataCiteSpider",
        "isni":            "uraas.spiders.sources.isni_spider.ISNISpider",
    }

    # "all" = every web-discovery spider (excludes "oai" which reads FROM the IR,
    # and "isni" which is an identity-enrichment spider, not a paper/dataset source)
    ALL_WEB_SPIDERS = [
        "openalex", "crossref", "semantic_scholar", "europepmc",
        "core", "pubmed", "openaire", "doaj", "ajol", "arxiv", "orcid",
        "datacite",
    ]

    if args.spider == "all":
        spider_names_to_run = ALL_WEB_SPIDERS
        # Divide target across spiders so total ≈ requested target
        per_spider_target = max(1, args.target // len(spider_names_to_run))
    else:
        spider_names_to_run = [args.spider]
        per_spider_target = args.target

    # Validate + import all spider classes up front so errors appear early
    spider_classes = {}
    for sname in spider_names_to_run:
        path = spider_map.get(sname)
        if not path:
            print(f"\n[ERR] Spider '{sname}' not supported", flush=True)
            return 1
        mod_path, cls_name = path.rsplit(".", 1)
        mod = __import__(mod_path, fromlist=[cls_name])
        spider_classes[sname] = getattr(mod, cls_name)

    # Legacy single-spider variable (used below)
    spider_class = spider_classes.get(spider_names_to_run[0])

    for inst in valid_institutions:
        config = registry.get(inst)
        print(f"  [VALID] {config.name} ({config.short_name})", flush=True)
        print(f"    ROR: {config.ror}", flush=True)
        print(f"    Staff: {len(config.staff_names)}", flush=True)

    if not valid_institutions:
        print("\n[ERR] No valid institutions found. Exiting.", flush=True)
        return 1

    print(f"\n{len(valid_institutions)} institution(s) validated", flush=True)
    print("=" * 60, flush=True)

    # Schedule crawls — ONE CrawlerProcess for ALL institutions
    print(f"\nScheduling crawls...", flush=True)
    settings = get_project_settings()
    settings.set(
        "ITEM_PIPELINES",
        {
            "uraas.pipelines.database.DatabaseStoragePipeline": 300,
        },
    )
    settings.set("LOG_LEVEL", "INFO")
    settings.set("LOG_SCRAPED_ITEMS", False)
    settings.set("TELNETCONSOLE_ENABLED", False)

    process = CrawlerProcess(settings)

    print(f"  Boost special collections: {args.boost_special}", flush=True)
    print(f"  SC-only mode: {args.sc_only}", flush=True)
    print(f"  Spiders: {', '.join(spider_names_to_run)}", flush=True)

    for inst in valid_institutions:
        cfg = registry.get(inst)
        print(f"  -> {cfg.name}", flush=True)
        for sname in spider_names_to_run:
            scls = spider_classes[sname]
            if sname == "oai":
                process.crawl(
                    scls,
                    institution=inst,
                    target=per_spider_target,
                    from_date=args.from_date,
                    until_date=args.until_date,
                )
            elif sname == "isni":
                # Identity-enrichment spider: no target/boost_special/sc_only —
                # it writes directly to Author.isni and yields no pipeline items.
                process.crawl(scls, institution=inst)
            else:
                process.crawl(
                    scls,
                    institution=inst,
                    target=per_spider_target,
                    boost_special=args.boost_special,
                    sc_only=args.sc_only,
                )

    print(
        f"\nStarting crawl for {len(valid_institutions)} institution(s)...", flush=True
    )
    print("=" * 60, flush=True)
    sys.stdout.flush()

    # Start crawling
    try:
        process.start()
        print("\n" + "=" * 60)
        print("CRAWL COMPLETED")
        print("=" * 60)
        return 0

    except KeyboardInterrupt:
        print("\n\n[ERR] Crawl interrupted by user")
        return 1

    except Exception as e:
        print(f"\n\n[ERR] Crawl failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
