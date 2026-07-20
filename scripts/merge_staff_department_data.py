"""One-time (re-runnable) merge: backfill department/faculty on
data/unilag_staff.json (the rich, ORCID-bearing file institutions/unilag.json
actually points at) from data/unilag_staff_detailed.json (an older scrape
that has department/faculty for ~3100 people but no reliable ORCID linkage
for most of them, and isn't wired into any current script).

harvest_staff_openalex.py — the script that actually (re)populates
unilag_staff.json — deliberately leaves department/faculty as None (see its
own comment: "We can't get concepts easily from works authorships without
extra queries, so we will leave faculty and department empty for now").
That's why every one of the 500 records currently has null department/faculty
even though a richer, if uneven-quality, source already exists on disk.

Matches by ORCID first (reliable identity key), falling back to normalized
name for the ~40% of unilag_staff.json records without ORCID. Never
overwrites a non-empty value.

Usage:
    python scripts/merge_staff_department_data.py            # DRY RUN
    python scripts/merge_staff_department_data.py --apply
"""

import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(BASE, "data", "unilag_staff.json")
SOURCE = os.path.join(BASE, "data", "unilag_staff_detailed.json")


def _norm_orcid(v):
    if not v:
        return None
    return v.replace("https://orcid.org/", "").strip() or None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    with open(TARGET, "r", encoding="utf-8") as f:
        target = json.load(f)
    with open(SOURCE, "r", encoding="utf-8") as f:
        source = json.load(f)

    by_orcid = {}
    by_name = {}
    for rec in source:
        orcid = _norm_orcid(rec.get("orcid"))
        name_key = (rec.get("name") or "").strip().lower()
        if not (rec.get("department") or rec.get("faculty")):
            continue
        if orcid and orcid not in by_orcid:
            by_orcid[orcid] = rec
        if name_key and name_key not in by_name:
            by_name[name_key] = rec

    filled_orcid = filled_name = 0
    for rec in target:
        if rec.get("department") and rec.get("faculty"):
            continue
        match = by_orcid.get(_norm_orcid(rec.get("orcid")))
        matched_via = "orcid"
        if not match:
            match = by_name.get((rec.get("name") or "").strip().lower())
            matched_via = "name"
        if not match:
            continue
        changed = False
        if not rec.get("department") and match.get("department"):
            rec["department"] = match["department"]
            changed = True
        if not rec.get("faculty") and match.get("faculty"):
            rec["faculty"] = match["faculty"]
            changed = True
        if changed:
            if matched_via == "orcid":
                filled_orcid += 1
            else:
                filled_name += 1

    total_filled = filled_orcid + filled_name
    still_missing = sum(1 for r in target if not r.get("department"))
    print(f"Target records: {len(target)}")
    print(f"Filled via ORCID match: {filled_orcid}")
    print(f"Filled via name match:  {filled_name}")
    print(f"Total filled: {total_filled}")
    print(f"Still missing department after merge: {still_missing}")

    if not args.apply:
        print("\n[DRY RUN] No changes written. Re-run with --apply.")
        return 0

    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(target, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {TARGET}")
    return 0


if __name__ == "__main__":
    main()
