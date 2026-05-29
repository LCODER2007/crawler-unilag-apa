"""
Staff Harvester — fetches real staff names, ORCIDs, departments from OpenAlex
for every configured institution. Saves enriched JSON to data/{inst}_staff.json.

Usage:
    python scripts/harvest_staff_openalex.py                  # all institutions
    python scripts/harvest_staff_openalex.py --institution unilag
    python scripts/harvest_staff_openalex.py --dry-run        # just print counts
"""

import os, sys, json, time, argparse, logging
import urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from uraas.config.institutions import get_registry, reset_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org"
MAILTO = "uraas-bot@research.edu.ng"
MAX_AUTHORS = 500  # cap per institution to avoid very long runs
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
    Harvest staff by looking at recent works from the institution on OpenAlex.
    Extracts unique authors from the authorships array.
    Returns list of rich staff dicts: {name, orcid, department, faculty, openalex_id, paper_count}
    """
    ror_url = inst_config.ror
    inst_name = inst_config.name
    log.info(f"Harvesting staff for {inst_name} (ROR: {ror_url}) …")

    unique_staff = {}
    cursor = "*"
    page = 0
    max_pages = 50  # Limit to 50 pages (10k works max) to avoid running forever

    while len(unique_staff) < MAX_AUTHORS and page < max_pages:
        # We query the works endpoint using the exact ROR url
        url = (
            f"{OPENALEX_BASE}/works"
            f"?filter=institutions.ror:{urllib.parse.quote(ror_url)}"
            f"&select=authorships"
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

        for work in results:
            for authorship in work.get("authorships", []):
                # Ensure the author is affiliated with our target institution for this work
                is_affiliated = False
                for inst in authorship.get("institutions", []):
                    if inst.get("ror") == ror_url:
                        is_affiliated = True
                        break

                if not is_affiliated:
                    continue

                author = authorship.get("author", {})
                aid = author.get("id")
                if not aid or aid in unique_staff:
                    if aid in unique_staff:
                        unique_staff[aid]["paper_count"] += 1
                    continue

                name = author.get("display_name", "").strip()
                if not name:
                    continue

                orcid_url = author.get("orcid", "")
                orcid = (
                    orcid_url.replace("https://orcid.org/", "") if orcid_url else None
                )

                # We can't get concepts easily from works authorships without extra queries,
                # so we will leave faculty and department empty for now.

                unique_staff[aid] = {
                    "name": name,
                    "orcid": orcid,
                    "department": None,
                    "faculty": None,
                    "openalex_id": aid.replace("https://openalex.org/", ""),
                    "paper_count": 1,
                }

                if len(unique_staff) >= MAX_AUTHORS:
                    break

            if len(unique_staff) >= MAX_AUTHORS:
                break

        log.info(
            f"  Page {page+1}: Processed {len(results)} works | Unique staff so far: {len(unique_staff)}"
        )
        page += 1
        time.sleep(DELAY)

        meta = data.get("meta", {})
        cursor = meta.get("next_cursor")
        if not cursor:
            break

    staff_list = list(unique_staff.values())
    log.info(f"  Harvested {len(staff_list)} staff for {inst_name}")
    return staff_list


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
    """Save staff list to data/{short_name_lower}_staff.json"""
    short = inst_config.short_name.lower()
    # Resolve base directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(base_dir, "data", f"{short}_staff.json")

    if dry_run:
        log.info(f"[DRY-RUN] Would save {len(staff)} staff records to {out_path}")
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(staff, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(staff)} staff records → {out_path}")


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
