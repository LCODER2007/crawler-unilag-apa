"""Pull the DOCiD corpus into a deployed URAAS instance.

DOCiD's records have to be in URAAS before URAAS can serve keywords and
citations over them. The Space has no shell, so this drives the admin HTTP
endpoints from a workstation.

    python scripts/ingest_docid_to_live.py

Credentials come from URAAS_ADMIN_USERNAME and URAAS_ADMIN_PASSWORD when set,
and from an interactive prompt otherwise. Nothing is read from the command
line, so the password never lands in shell history.

Pacing
------
The Space runs without a Celery broker, so its ingest runs inline in a
background thread, one upstream request per record at roughly 0.7s. This
therefore submits the work in bounded chunks and waits for each to land
rather than asking for the whole corpus at once: a single unbounded request
would be refused, and a very long one risks the Space sleeping underneath it.

Re-running is safe. Ingest upserts on (source_repository, source_record_id),
so a chunk that partly completed is simply finished on the next pass.
"""

import argparse
import getpass
import os
import sys
import time

import requests

DEFAULT_BASE_URL = "https://lordkiki-apa-uraas.hf.space"

WAKE_TIMEOUT_S = 120
# How long to let one chunk run before checking on it. A chunk of N pages at
# `page_size` records is about 0.7s per record.
POLL_INTERVAL_S = 30
# Give up on a chunk that has added nothing for this many consecutive polls.
QUIET_POLLS_TO_GIVE_UP = 6


def credentials():
    username = os.getenv("URAAS_ADMIN_USERNAME") or input("admin username: ").strip()
    password = os.getenv("URAAS_ADMIN_PASSWORD") or getpass.getpass("admin password: ")
    return username, password


def coverage(session, base_url):
    r = session.get(f"{base_url}/api/docid/ingest/coverage", timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--page-size", type=int, default=100, help="records per page (default 100)"
    )
    parser.add_argument(
        "--pages-per-chunk",
        type=int,
        default=5,
        help="pages submitted per request (default 5)",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=0,
        help="stop after this many chunks; 0 means run until the corpus is covered",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    session = requests.Session()

    print(f"Waking {base_url} ...")
    try:
        session.get(f"{base_url}/health", timeout=WAKE_TIMEOUT_S).raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"could not reach {base_url}: {exc}")

    username, password = credentials()
    r = session.post(
        f"{base_url}/login",
        data={"username": username, "password": password},
        timeout=60,
        allow_redirects=False,
    )
    if r.status_code != 302:
        sys.exit(f"login failed ({r.status_code}) - check the admin credentials")
    print("Logged in.")

    start = coverage(session, base_url)
    remote_total = start.get("remote_total") or 0
    print(
        f"Before: {start['records_held']} of {remote_total} records held "
        f"({start.get('coverage_pct')}%)"
    )
    if start.get("queue", {}).get("eager"):
        print(
            "No Celery broker on this instance - the ingest runs inline in a "
            "background thread. Expect roughly 0.7s per record."
        )

    chunk = 0
    start_page = start["records_held"] // args.page_size + 1
    while True:
        chunk += 1
        if args.max_chunks and chunk > args.max_chunks:
            print(f"Stopping after {args.max_chunks} chunk(s) as requested.")
            break

        held_before = coverage(session, base_url)["records_held"]
        if remote_total and held_before >= remote_total:
            print("Corpus fully ingested.")
            break

        print(
            f"\nChunk {chunk}: pages {start_page}..{start_page + args.pages_per_chunk - 1} "
            f"at page_size={args.page_size}"
        )
        r = session.post(
            f"{base_url}/api/admin/docid/ingest/backfill",
            json={
                "start_page": start_page,
                "page_size": args.page_size,
                "max_pages": args.pages_per_chunk,
            },
            timeout=120,
        )
        if r.status_code != 200:
            sys.exit(f"backfill rejected ({r.status_code}): {r.text[:300]}")

        last = held_before
        quiet = 0
        while quiet < QUIET_POLLS_TO_GIVE_UP:
            time.sleep(POLL_INTERVAL_S)
            try:
                held = coverage(session, base_url)["records_held"]
            except requests.RequestException as exc:
                print(f"  poll failed ({exc}), retrying")
                continue
            if held == last:
                quiet += 1
                print(f"  {held} held (unchanged {quiet}/{QUIET_POLLS_TO_GIVE_UP})")
            else:
                quiet = 0
                print(f"  {held} held (+{held - last})")
            last = held
            if remote_total and held >= remote_total:
                break

        start_page += args.pages_per_chunk
        if last == held_before:
            print("  chunk added nothing - stopping rather than looping.")
            break

    end = coverage(session, base_url)
    print(
        f"\nAfter: {end['records_held']} of {end.get('remote_total')} records held "
        f"({end.get('coverage_pct')}%), "
        f"{end['records_with_creators']} with creators"
    )
    print(f"Added this run: {end['records_held'] - start['records_held']}")
    print("\nEnrichment is now served at:")
    print(f"  {base_url}/api/docid/enrichment/<their_publication_id>")
    print(f"  {base_url}/api/docid/enrichment?page=1&page_size=100")


if __name__ == "__main__":
    main()
