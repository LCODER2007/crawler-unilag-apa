"""Backfill Item.dc_rights (and the linked File.access_policy) from
Unpaywall's open-access verdict, for records crawled before the spiders
started recording it.

Why this exists: Item.dc_rights has a model default of
"info:eu-repo/semantics/restrictedAccess" and, until 2026-09, *nothing in
the codebase ever wrote it*. Every OA metric in the dashboard
(oa_percentage, open-access-breakdown, impact-metrics' oa_rate, the is_oa
flag in search results, the OA column in CSV exports) filters on
dc_rights LIKE '%openAccess%', so all of them silently reported 0% — not
because the papers are closed, but because the field was never populated.
It also made /api/papers/<id>/download return 403 for every non-admin
caller, including partner API keys, since the download gate reads the same
field.

The spiders now set dc_rights at crawl time from each source's own OA
signal (OpenAlex open_access.is_oa, EuropePMC isOpenAccess, DOAJ/arXiv by
definition, CORE downloadUrl presence). This script fixes the records that
predate that change.

Usage:
    python scripts/backfill_open_access.py                # DRY RUN
    python scripts/backfill_open_access.py --apply
    python scripts/backfill_open_access.py --apply --limit 50
"""

import argparse
import os
import sys
import time

import requests

# This collection is full of Yoruba/Igbo/Hausa titles (ọ, ẹ, ṣ, à ...) and a
# Windows console defaults to cp1252, which cannot encode them — printing a
# progress line for such a title raises UnicodeEncodeError and kills the run
# mid-way (hit for real on "Gospel Àpàlà music ..."). Force UTF-8 with
# replacement so progress output can never abort the backfill itself.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config import config
from uraas.database import File, Item, SessionLocal

_UNPAYWALL_API = "https://api.unpaywall.org/v2"
_TIMEOUT = 15
_OA = "info:eu-repo/semantics/openAccess"
_CLOSED = "info:eu-repo/semantics/restrictedAccess"


def fetch_oa_status(doi: str):
    """Return (is_oa, oa_status, pdf_url) from Unpaywall, or (None, None,
    None) on failure.

    None for is_oa means "couldn't determine" and is deliberately distinct
    from False — an API failure must never downgrade a record we already
    believe is open access.

    The same response also carries best_oa_location, so the full-text URL
    comes free with the call we're already making. That matters: an item can
    be open access and still be undownloadable simply because no pdf_url was
    ever captured for it (54 of 206 records on the live Space had one, 57
    more were open access without one).
    """
    try:
        r = requests.get(
            f"{_UNPAYWALL_API}/{doi}",
            params={"email": config.OPENALEX_MAILTO},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None, None, None
        data = r.json()
        loc = data.get("best_oa_location") or {}
        pdf_url = loc.get("url_for_pdf") or loc.get("url") or None
        return bool(data.get("is_oa")), data.get("oa_status"), pdf_url
    except Exception:
        return None, None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max items to check this run"
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        # Two kinds of record need this: ones whose access level was never
        # resolved, and ones already known to be open access but with no
        # full-text URL captured — the latter are open access yet still
        # undownloadable, which is just as much a gap.
        candidates = (
            session.query(Item)
            .filter(Item.doi.isnot(None))
            .filter(Item.doi != "")
            .filter(
                (Item.dc_rights == _CLOSED)
                | (Item.pdf_url.is_(None))
                | (Item.pdf_url == "")
            )
            .all()
        )
        print(f"Items needing access status and/or a full-text URL: {len(candidates)}")
        if args.limit:
            candidates = candidates[: args.limit]
            print(f"Limited to first {len(candidates)} for this run")

        if not args.apply:
            print("[DRY RUN] Would query Unpaywall for these. Re-run with --apply.")
            return 0

        opened = linked = checked = 0
        for it in candidates:
            is_oa, oa_status, pdf_url = fetch_oa_status(it.doi)
            checked += 1
            if is_oa:
                if it.dc_rights != _OA:
                    it.dc_rights = _OA
                    opened += 1
                # Keep any downloaded file's policy consistent with the item.
                for f in session.query(File).filter_by(item_id=it.id).all():
                    f.access_policy = "Public"
                # An open-access record with no full-text URL can't actually
                # be fetched — fill it in while we have the answer.
                if pdf_url and not (it.pdf_url or "").strip():
                    it.pdf_url = pdf_url
                    linked += 1
                print(f"  OA   id={it.id} ({oa_status})  {(it.title or '')[:55]}")
            time.sleep(0.3)  # polite: Unpaywall asks for reasonable pacing
        session.commit()
        print(
            f"\nDONE. Checked: {checked}   Newly open access: {opened}   "
            f"Full-text URLs added: {linked}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
