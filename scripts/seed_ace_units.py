"""
Seed Africa Centres of Excellence (ACE) as Community rows (unit_type="ace"),
each minted a self-assigned persistent ID (PMD) — the same role ROR plays
for institutions, minted locally via ark_generator (deterministic, no
network access, idempotent on re-run).

This script does NOT ship with any hardcoded ACE names — supply the real
list at UNILAG (and any other institution) via a JSON input file:

    [
      {"name": "ACE for Genomics of Non-Communicable Diseases", "institution": "unilag"},
      {"name": "Another ACE Name", "institution": "unilag", "ror_id": "https://ror.org/..."}
    ]

`institution` must match a short_name known to uraas/config/institutions.py.
`ror_id` is optional — only set it if the ACE has been assigned its own ROR.

Usage:
    python scripts/seed_ace_units.py ace_units.json            # DRY RUN
    python scripts/seed_ace_units.py ace_units.json --apply
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config.institutions import get_registry
from uraas.database import Community, SessionLocal
from uraas.utils.ark_generator import ark_generator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="JSON file listing ACE units to seed")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    with open(args.input_file, encoding="utf-8") as f:
        ace_units = json.load(f)

    if not isinstance(ace_units, list) or not ace_units:
        print("Input file must contain a non-empty JSON list of ACE units.")
        return 1

    registry = get_registry()
    session = SessionLocal()
    try:
        planned = []
        for entry in ace_units:
            name = entry.get("name")
            inst_short_name = entry.get("institution")
            if not name or not inst_short_name:
                print(f"SKIP (missing name/institution): {entry}")
                continue

            institution_config = registry.get(inst_short_name)
            if not institution_config:
                print(f"SKIP (unknown institution {inst_short_name!r}): {name}")
                continue

            existing = session.query(Community).filter_by(name=name).first()
            seed = f"ACE|{institution_config.ror}|{name}"
            pmd = ark_generator.mint(seed)
            planned.append((entry, institution_config, existing, pmd))

        print("=" * 64)
        for entry, institution_config, existing, pmd in planned:
            status = "UPDATE" if existing else "CREATE"
            print(f"[{status}] {entry['name']} ({institution_config.name}) -> pmd={pmd}")
        print("=" * 64)
        print(f"{len(planned)} ACE unit(s) to process")

        if not args.apply:
            print("[DRY RUN] No writes. Re-run with --apply.")
            return 0

        now = datetime.utcnow()
        created = updated = 0
        for entry, institution_config, existing, pmd in planned:
            if existing:
                existing.unit_type = "ace"
                existing.institution = institution_config.name
                existing.ror = institution_config.ror
                if entry.get("ror_id"):
                    existing.ror_id = entry["ror_id"]
                if not existing.pmd:
                    existing.pmd = pmd
                    existing.pmd_assigned_at = now
                updated += 1
            else:
                community = Community(
                    name=entry["name"],
                    ror_id=entry.get("ror_id"),
                    institution=institution_config.name,
                    ror=institution_config.ror,
                    unit_type="ace",
                    pmd=pmd,
                    pmd_assigned_at=now,
                )
                session.add(community)
                created += 1
        session.commit()

        print(f"DONE. Created: {created}   Updated: {updated}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
