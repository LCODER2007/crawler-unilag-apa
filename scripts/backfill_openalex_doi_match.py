"""
Backfill missing DOIs on existing Special Collections items via fuzzy
title+author matching against OpenAlex.

Some sources (AJOL HTML scrapes especially, and OAI-PMH records with
incomplete dc:identifier metadata) yield items with no DOI at all. This
script looks each one up on OpenAlex by title, and — mirroring
uraas/spiders/sources/isni_spider.py's "exactly one confident candidate or
skip" philosophy — only accepts a match when it's unambiguous. It never
guesses: a wrong DOI attached to the wrong paper is worse than a missing one.

On accept, backfills doi / openalex_id / cited_by_count / counts_by_year.
Does NOT touch item_affiliations — run scripts/backfill_collaboration_data.py
afterward for that (it's idempotent/skip-if-already-populated, so the two
scripts compose naturally as sequential passes).

Funder/grant enrichment is deliberately out of scope here — it needs a new
Item.funders column (not yet added) and is much simpler once a DOI exists
(direct OpenAlex work lookup by DOI, no fuzzy matching needed at all), so
it belongs in a follow-up script that runs after this one.

Usage:
    python scripts/backfill_openalex_doi_match.py                # DRY RUN
    python scripts/backfill_openalex_doi_match.py --apply
    python scripts/backfill_openalex_doi_match.py --apply --limit 50
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thefuzz import fuzz

from uraas.database import Item, SessionLocal
from uraas.utils.analytics_cache import analytics_cache
from uraas.utils.openalex_client import oa_get

TITLE_THRESHOLD = 92  # near-unique signal — strict on purpose
AUTHOR_THRESHOLD = (
    80  # corroborating only — loose to tolerate name-order/transliteration variance
)
CANDIDATES_PER_QUERY = 5
SELECT = "id,doi,title,authorships,cited_by_count,counts_by_year"


def _first_author_name(item) -> str:
    """Best-effort 'first' author. item_authors has no sequence/order column,
    so this is a heuristic (usually reflects insertion order), used only as
    a corroborating signal — never the primary accept/reject gate."""
    authors = list(item.authors)
    return authors[0].name if authors and authors[0].name else ""


def _candidate_author_names(work) -> list:
    return [
        (a.get("author", {}) or {}).get("display_name", "")
        for a in work.get("authorships", [])
        if (a.get("author", {}) or {}).get("display_name")
    ]


def find_match(title: str, local_author: str):
    """Return (work_or_None, title_sim, num_candidates_seen, num_qualifying)."""
    data = oa_get(
        "/works",
        {"search": title, "select": SELECT, "per-page": CANDIDATES_PER_QUERY},
    )
    results = (data or {}).get("results", [])
    qualifying = []
    for work in results:
        cand_title = work.get("title") or ""
        title_sim = fuzz.token_sort_ratio(title.lower(), cand_title.lower())
        if title_sim < TITLE_THRESHOLD:
            continue
        if local_author:
            cand_names = _candidate_author_names(work)
            author_sim = max(
                (fuzz.ratio(local_author.lower(), n.lower()) for n in cand_names),
                default=0,
            )
            if author_sim < AUTHOR_THRESHOLD:
                continue
        qualifying.append((work, title_sim))

    if len(qualifying) == 1:
        work, title_sim = qualifying[0]
        return work, title_sim, len(results), 1
    return None, 0, len(results), len(qualifying)


def apply_match(item, work):
    doi = (work.get("doi") or "").replace("https://doi.org/", "").strip()
    if not doi:
        return False
    item.doi = doi
    item.openalex_id = work.get("id", "").replace("https://openalex.org/", "") or None
    item.cited_by_count = work.get("cited_by_count", 0) or 0
    cby = work.get("counts_by_year") or []
    item.counts_by_year = json.dumps(cby) if cby else None
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Max items to process (0 = all)"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        q = session.query(Item).filter(
            Item.doi.is_(None), Item.special_collection_score > 0
        )
        items = q.all()
        if args.limit:
            items = items[: args.limit]

        print("=" * 64)
        print(f"SC items missing DOI: {len(items)}")
        print("=" * 64)
        if not args.apply:
            print("[DRY RUN] No API calls or writes. Re-run with --apply.")
            return 0

        matched = ambiguous = not_found = 0
        for i, item in enumerate(items, 1):
            title = item.title or ""
            if not title.strip():
                continue
            local_author = _first_author_name(item)
            work, title_sim, n_seen, n_qualifying = find_match(title, local_author)

            if work and apply_match(item, work):
                matched += 1
                print(
                    f"  [{i}/{len(items)}] MATCH ({title_sim}%): "
                    f"{title[:70]!r} -> {item.doi}"
                )
            elif n_seen == 0:
                not_found += 1
            else:
                ambiguous += 1
                print(
                    f"  [{i}/{len(items)}] SKIP ({n_qualifying}/{n_seen} qualifying): "
                    f"{title[:70]!r}"
                )

            if i % 10 == 0:
                session.commit()
            time.sleep(0.5)  # OpenAlex polite pool

        session.commit()
        analytics_cache.invalidate_all()

        print("\n" + "=" * 64)
        print(
            f"DONE. matched={matched}  ambiguous/skipped={ambiguous}  "
            f"not_found={not_found}"
        )
        print("=" * 64)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
