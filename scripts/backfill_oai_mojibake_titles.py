"""Repair OAI-PMH-sourced titles corrupted by UNILAG DSpace's OAI encoding
bug (see uraas/spiders/sources/oai_spider.py's _looks_mojibake() docstring
for the full diagnosis — confirmed 2026-07-19: the OAI feed replaces
non-ASCII bytes with literal "?" even though it declares charset=UTF-8,
while the SAME record's REST API representation has correct Unicode).

The crawler itself is now fixed going forward (oai_spider.py repairs titles
at harvest time), but that doesn't touch rows already stored with the bug.
This finds them and re-fetches the clean title from the REST
/api/pid/find?id=hdl:... endpoint, keyed off the item's stored handle URL.

Usage:
    python scripts/backfill_oai_mojibake_titles.py            # DRY RUN
    python scripts/backfill_oai_mojibake_titles.py --apply
"""

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from uraas.config.institutions import get_registry
from uraas.database import Item, SessionLocal

_MOJIBAKE_RE = re.compile(r"[a-zA-Z]\?|\?[a-zA-Z]")


def _looks_mojibake(text: str) -> bool:
    return bool(text) and bool(_MOJIBAKE_RE.search(text))


def _handle_from_url(url: str) -> str:
    if not url or "/handle/" not in url:
        return ""
    return url.split("/handle/", 1)[-1].strip("/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        candidates = (
            session.query(Item)
            .filter(Item.source_repository.like("%OAI-PMH%"))
            .all()
        )
        corrupted = [it for it in candidates if _looks_mojibake(it.title or "")]
        print(f"OAI-sourced items: {len(candidates)}   mojibake titles: {len(corrupted)}")

        registry = get_registry()
        # Item.institution stores the display name (e.g. "University of
        # Lagos"), not the registry's short-name key ("unilag") that
        # registry.get() expects — match by name instead.
        by_name = {c.name: c for c in registry.list_all()}

        fixed = failed = 0
        for it in corrupted:
            handle = _handle_from_url(it.url or "")
            # REST base must come from the institution's configured OAI
            # endpoint (api-ir.unilag.edu.ng), NOT guessed from the item's
            # own stored url — DSpace's public handle-resolver domain
            # (ir.unilag.edu.ng) is a different host from the REST API.
            inst_cfg = by_name.get(it.institution) if it.institution else None
            rest_base = (
                inst_cfg.oai_endpoint.split("/oai/")[0]
                if inst_cfg and inst_cfg.oai_endpoint
                else ""
            )
            if not handle or not rest_base:
                print(f"  id={it.id}: no handle/oai_endpoint (url={it.url!r}, institution={it.institution!r}), cannot repair")
                failed += 1
                continue
            try:
                r = requests.get(
                    f"{rest_base}/api/pid/find",
                    params={"id": f"hdl:{handle}"},
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
                r.raise_for_status()
                clean_title = (r.json() or {}).get("name", "").strip()
            except Exception as e:
                print(f"  id={it.id}: REST lookup failed: {e}")
                failed += 1
                continue

            if not clean_title or _looks_mojibake(clean_title):
                print(f"  id={it.id}: REST also returned unusable title: {clean_title!r}")
                failed += 1
                continue

            def _safe(s):
                return s.encode("ascii", errors="replace").decode("ascii")

            print(f"  id={it.id}: {_safe(it.title)!r} -> {_safe(clean_title)!r}")
            if args.apply:
                it.title = clean_title
                it.dc_title = clean_title
            fixed += 1
            time.sleep(0.3)

        print(f"\nWould fix: {fixed}   Unrecoverable: {failed}")
        if not args.apply:
            print("\n[DRY RUN] No changes written. Re-run with --apply.")
            return 0

        session.commit()
        print(f"\nDONE. {fixed} titles repaired.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
