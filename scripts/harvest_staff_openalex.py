"""
Staff Harvester — fetches real staff names, ORCIDs, departments from OpenAlex
for every configured institution. Saves enriched JSON to data/{inst}_staff.json.

Usage:
    python scripts/harvest_staff_openalex.py                  # all institutions
    python scripts/harvest_staff_openalex.py --institution unilag
    python scripts/harvest_staff_openalex.py --dry-run        # just print counts
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uraas.config.institutions import get_registry, reset_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org"
MAILTO = "uraas-bot@research.edu.ng"
DELAY = 0.5  # seconds between requests (polite)


def _get(url: str, retries: int = 3) -> dict:
    """Simple urllib GET with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"URAAS/1.0 (mailto:{MAILTO})"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                log.warning(f"Rate limited, waiting {wait}s …")
                time.sleep(wait)
            else:
                log.error(f"HTTP {e.code} for {url}")
                break
        except Exception as e:
            log.error(f"Request error ({attempt+1}/{retries}): {e}")
            time.sleep(2)
    return {}


def harvest_institution(inst_config, dry_run: bool = False) -> list:
    """
    Harvest researchers via OpenAlex's direct /authors endpoint, filtered by
    `last_known_institutions.ror` (an author's most recent known
    affiliation — the closest OpenAlex signal to "current staff").

    This replaced an approach that derived unique authors indirectly from a
    500-author-capped, 50-page scan of individual WORKS — which, for a
    university the size of UNILAG, was capturing under 5% of its real
    author population. Live-checked 2026-07-20: `affiliations.institution.
    ror:05rk03822` (ever affiliated) = 16,557 authors;
    `last_known_institutions.ror:05rk03822` (current/most-recent) = 11,854.
    Neither number is a perfect "official current academic staff count" —
    OpenAlex has no such registry, and this authorship-derived figure
    necessarily includes some postgraduate students and historically-
    affiliated researchers alongside genuine current staff — but it's the
    most complete data-driven approximation available, and is what
    downstream ORCID-employment verification (see orcid_spider.py) is
    designed to further refine per-paper, not something to solve by
    capping the roster small.

    Returns list of rich staff dicts:
        {name, orcid, department, faculty, openalex_id, paper_count}
    (department/faculty are always None here — filled in by
    scripts/merge_staff_department_data.py and preserved across re-harvests
    by save_staff()'s merge-by-ORCID/name logic.)
    """
    inst_name = inst_config.name
    log.info(f"Harvesting authors for {inst_name} (ROR: {inst_config.ror}) via /authors API...")

    staff = []
    cursor = "*"
    page = 0

    while True:
        # Unlike institutions.ror (used elsewhere in this codebase, e.g.
        # openalex_spider.py), last_known_institutions.ror requires the FULL
        # "https://ror.org/..." form — the bare short ID silently matches
        # zero authors instead of erroring. Confirmed live 2026-07-20.
        url = (
            f"{OPENALEX_BASE}/authors"
            f"?filter=last_known_institutions.ror:{urllib.parse.quote(inst_config.ror)}"
            f"&select=id,display_name,orcid,works_count"
            f"&per-page=200"
            f"&cursor={urllib.parse.quote(cursor)}"
            f"&mailto={MAILTO}"
        )
        data = _get(url)
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        for author in results:
            name = (author.get("display_name") or "").strip()
            if not name:
                continue
            orcid_url = author.get("orcid") or ""
            orcid = orcid_url.replace("https://orcid.org/", "") if orcid_url else None
            aid = (author.get("id") or "").replace("https://openalex.org/", "")
            staff.append({
                "name": name,
                "orcid": orcid,
                "department": None,
                "faculty": None,
                "openalex_id": aid,
                "paper_count": author.get("works_count", 0),
            })

        page += 1
        log.info(f"  Page {page}: +{len(results)} authors | total so far: {len(staff)}")
        time.sleep(DELAY)

        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break

    log.info(f"  Harvested {len(staff)} authors for {inst_name}")
    return staff


def _map_concept_to_faculty(concept: str, faculties: list) -> str:
    """Rough concept→faculty mapping via keyword overlap."""
    concept_lower = concept.lower()
    faculty_map = {
        "medicine": ["health", "medicine", "clinical", "nursing", "pharmacy", "dental"],
        "engineering": [
            "engineering",
            "technology",
            "mechanical",
            "electrical",
            "civil",
            "chemical",
        ],
        "science": [
            "biology",
            "chemistry",
            "physics",
            "mathematics",
            "statistics",
            "computer",
        ],
        "arts": [
            "literature",
            "linguistics",
            "language",
            "history",
            "philosophy",
            "arts",
        ],
        "social": [
            "sociology",
            "economics",
            "political",
            "psychology",
            "anthropology",
            "social",
        ],
        "law": ["law", "legal", "jurisprudence", "criminology"],
        "education": ["education", "pedagogy", "teaching", "curriculum"],
        "agriculture": ["agriculture", "botany", "zoology", "ecology", "forestry"],
        "management": ["business", "management", "accounting", "finance", "marketing"],
        "environmental": [
            "environment",
            "urban",
            "planning",
            "geography",
            "architecture",
        ],
    }
    for fac_key, keywords in faculty_map.items():
        if any(kw in concept_lower for kw in keywords):
            # Try to match to actual faculty names
            for f in faculties:
                if fac_key in f.lower() or any(kw in f.lower() for kw in keywords):
                    return f
    return None


def get_orcid_details(orcid: str) -> dict:
    """Fetch name and affiliation details from ORCID public API."""
    url = f"https://pub.orcid.org/v3.0/{orcid}/person"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"URAAS/1.0 (mailto:{MAILTO})",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        affiliations = data.get("activities-summary", {})
        return {"orcid": orcid}
    except Exception:
        return {}


def save_staff(inst_config, staff: list, dry_run: bool = False):
    """Save staff list to data/{short_name_lower}_staff.json.

    Merges onto any existing file by ORCID (falling back to normalized name)
    instead of overwriting outright — a re-harvest must not wipe
    department/faculty data already populated by
    scripts/merge_staff_department_data.py or discovered live via ORCID
    /employments lookups in orcid_spider.py.
    """
    short = inst_config.short_name.lower()
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(base_dir, "data", f"{short}_staff.json")

    existing_by_orcid, existing_by_name = {}, {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                for rec in json.load(f):
                    if rec.get("orcid"):
                        existing_by_orcid[rec["orcid"]] = rec
                    if rec.get("name"):
                        existing_by_name[rec["name"].strip().lower()] = rec
        except Exception as e:
            log.warning(f"Could not read existing {out_path} for merge: {e}")

    merged = []
    for rec in staff:
        prior = existing_by_orcid.get(rec.get("orcid")) or existing_by_name.get(
            rec["name"].strip().lower()
        )
        if prior:
            rec["department"] = rec.get("department") or prior.get("department")
            rec["faculty"] = rec.get("faculty") or prior.get("faculty")
        merged.append(rec)

    if dry_run:
        log.info(f"[DRY-RUN] Would save {len(merged)} staff records to {out_path}")
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(merged)} staff records → {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Harvest staff from OpenAlex for URAAS institutions"
    )
    parser.add_argument(
        "--institution",
        type=str,
        default=None,
        help="Single institution short name (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print counts without saving"
    )
    args = parser.parse_args()

    reset_registry()
    registry = get_registry()
    all_insts = registry.list_all()

    if args.institution:
        inst = registry.get(args.institution)
        if not inst:
            print(f"ERROR: Institution '{args.institution}' not found")
            sys.exit(1)
        target_insts = [inst]
    else:
        target_insts = all_insts

    print(f"\n{'='*60}")
    print(f"URAAS Staff Harvester — OpenAlex")
    print(f"Institutions: {len(target_insts)}")
    print(f"{'='*60}\n")

    summary = []
    for inst in target_insts:
        try:
            staff = harvest_institution(inst, dry_run=args.dry_run)
            orcid_count = sum(1 for s in staff if s.get("orcid"))
            save_staff(inst, staff, dry_run=args.dry_run)
            summary.append(
                {
                    "institution": inst.name,
                    "staff_total": len(staff),
                    "with_orcid": orcid_count,
                }
            )
        except Exception as e:
            log.error(f"Failed harvesting {inst.name}: {e}")
            summary.append(
                {"institution": inst.name, "staff_total": 0, "with_orcid": 0}
            )
        time.sleep(1)

    print(f"\n{'='*60}")
    print("HARVEST SUMMARY")
    print(f"{'='*60}")
    total_staff = 0
    total_orcid = 0
    for s in summary:
        print(
            f"  {s['institution']:<45} {s['staff_total']:>5} staff  {s['with_orcid']:>4} ORCID"
        )
        total_staff += s["staff_total"]
        total_orcid += s["with_orcid"]
    print(f"{'-'*60}")
    print(f"  {'TOTAL':<45} {total_staff:>5} staff  {total_orcid:>4} ORCID")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
