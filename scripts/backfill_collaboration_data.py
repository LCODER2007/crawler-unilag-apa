"""
Backfill collaboration + citation data for existing items from OpenAlex.

Re-fetches each item's OpenAlex record (batched 50 DOIs per request to
conserve API quota) and populates:
  - item_affiliations rows (institution / ROR / country per authorship)
  - items.coauthor_countries / african_country_count / is_intra_african
  - items.openalex_id / cited_by_count / counts_by_year

Usage:
    python scripts/backfill_collaboration_data.py                # DRY RUN
    python scripts/backfill_collaboration_data.py --apply
    python scripts/backfill_collaboration_data.py --apply --limit 500
    python scripts/backfill_collaboration_data.py --apply --force   # redo enriched rows

Idempotent: items that already have affiliation rows are skipped unless
--force. Respects ~1 req/sec. Set OPENALEX_API_KEY in the environment.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config.african_countries import african_countries_in
from uraas.database import Item, ItemAffiliation, SessionLocal
from uraas.utils.analytics_cache import analytics_cache
from uraas.utils.openalex_client import oa_get

BATCH = 50
SELECT = "id,doi,authorships,cited_by_count,counts_by_year"


def _norm_doi(doi: str) -> str:
    return (
        (doi or "")
        .replace("https://doi.org/", "")
        .replace("http://dx.doi.org/", "")
        .strip()
        .lower()
    )


def fetch_batch_by_doi(dois):
    """One OpenAlex call for up to 50 DOIs. Returns {normalized_doi: work}.

    DOIs are pipe-joined raw — requests URL-encodes the whole filter param;
    pre-quoting each DOI double-encodes and matches nothing."""
    flt = "doi:" + "|".join(dois)
    data = oa_get("/works", {"filter": flt, "select": SELECT, "per-page": BATCH})
    out = {}
    for work in (data or {}).get("results", []):
        nd = _norm_doi(work.get("doi", ""))
        if nd:
            out[nd] = work
    return out


def fetch_batch_by_openalex_id(ids):
    """One OpenAlex call for up to 50 OpenAlex work IDs."""
    flt = "openalex_id:" + "|".join(ids)
    data = oa_get("/works", {"filter": flt, "select": SELECT, "per-page": BATCH})
    out = {}
    for work in (data or {}).get("results", []):
        wid = work.get("id", "").replace("https://openalex.org/", "")
        if wid:
            out[wid] = work
    return out


def extract_affiliations(work):
    """(ror_short, name) -> {ror, name, country_code, author_count}."""
    rows = {}
    for authorship in work.get("authorships", []):
        for inst in authorship.get("institutions", []):
            name = inst.get("display_name", "") or ""
            ror = (inst.get("ror") or "").replace("https://ror.org/", "")
            cc = (inst.get("country_code") or "").upper()
            if not (name or ror):
                continue
            row = rows.setdefault(
                (ror, name),
                {"ror": ror, "name": name, "country_code": cc, "author_count": 0},
            )
            row["author_count"] += 1
            if cc and not row["country_code"]:
                row["country_code"] = cc
    return list(rows.values())


def apply_work(session, item, work):
    """Write affiliation rows + collaboration/citation columns for one item."""
    affs = extract_affiliations(work)

    # Idempotency: replace any existing affiliation rows for this item.
    session.query(ItemAffiliation).filter_by(item_id=item.id).delete()
    for aff in affs:
        session.add(
            ItemAffiliation(
                item_id=item.id,
                ror=(aff["ror"] or "")[:128] or None,
                institution_name=(aff["name"] or "")[:255] or None,
                country_code=(aff["country_code"] or "")[:2] or None,
                author_count=aff["author_count"],
            )
        )

    african = african_countries_in(a["country_code"] for a in affs)
    item.coauthor_countries = ",".join(african) or None
    item.african_country_count = len(african)
    item.is_intra_african = len(african) >= 2

    item.openalex_id = work.get("id", "").replace("https://openalex.org/", "") or None
    item.cited_by_count = work.get("cited_by_count", 0) or 0
    cby = work.get("counts_by_year") or []
    item.counts_by_year = json.dumps(cby) if cby else None
    return len(affs), item.is_intra_african


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    parser.add_argument("--limit", type=int, default=0, help="Max items to process (0 = all)")
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch items that already have affiliation data"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        q = session.query(Item)
        if not args.force:
            enriched = {i for (i,) in session.query(ItemAffiliation.item_id).distinct()}
        else:
            enriched = set()

        items = [
            it
            for it in q.all()
            if it.id not in enriched and (it.doi or "openalex.org" in (it.url or ""))
        ]
        skipped_no_id = q.count() - len(items) - len(enriched & {it.id for it in q})
        if args.limit:
            items = items[: args.limit]

        print("=" * 64)
        print(f"Items to enrich: {len(items)}  (already enriched, skipped: {len(enriched)})")
        print("=" * 64)
        if not args.apply:
            print("[DRY RUN] No API calls or writes. Re-run with --apply.")
            return 0

        by_doi = [it for it in items if it.doi]
        by_oaid = [
            it for it in items if not it.doi and "openalex.org" in (it.url or "")
        ]

        updated = intra = not_found = 0

        # ── DOI batches ──────────────────────────────────────────────────
        doi_map = {_norm_doi(it.doi): it for it in by_doi}
        doi_keys = list(doi_map)
        for start in range(0, len(doi_keys), BATCH):
            chunk = doi_keys[start : start + BATCH]
            works = fetch_batch_by_doi(chunk)
            for nd in chunk:
                it = doi_map[nd]
                work = works.get(nd)
                if not work:
                    not_found += 1
                    continue
                _, is_ia = apply_work(session, it, work)
                updated += 1
                intra += int(is_ia)
            session.commit()
            print(
                f"  [doi {start + len(chunk)}/{len(doi_keys)}] "
                f"updated={updated} intra_african={intra} not_found={not_found}"
            )
            time.sleep(1.0)

        # ── OpenAlex-ID batches (items without DOI) ──────────────────────
        oaid_map = {}
        for it in by_oaid:
            wid = (it.url or "").rstrip("/").split("/")[-1]
            if wid.startswith("W"):
                oaid_map[wid] = it
        oaid_keys = list(oaid_map)
        for start in range(0, len(oaid_keys), BATCH):
            chunk = oaid_keys[start : start + BATCH]
            works = fetch_batch_by_openalex_id(chunk)
            for wid in chunk:
                it = oaid_map[wid]
                work = works.get(wid)
                if not work:
                    not_found += 1
                    continue
                _, is_ia = apply_work(session, it, work)
                updated += 1
                intra += int(is_ia)
            session.commit()
            print(
                f"  [oaid {start + len(chunk)}/{len(oaid_keys)}] "
                f"updated={updated} intra_african={intra} not_found={not_found}"
            )
            time.sleep(1.0)

        analytics_cache.invalidate_all()
        total_ia = session.query(Item).filter(Item.is_intra_african.is_(True)).count()
        total = session.query(Item).count()
        print("\n" + "=" * 64)
        print(f"DONE. updated={updated}  not_found={not_found}")
        print(
            f"Repository intra-African collaboration: {total_ia}/{total} "
            f"({(total_ia / total * 100) if total else 0:.1f}%) — continental baseline ~8.4%"
        )
        print("=" * 64)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
