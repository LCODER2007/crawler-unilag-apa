"""Populate a deployed instance's citation graph.

The graph endpoints serve whatever has been synced; nothing syncs itself,
because a sync fans out to OpenAlex and writes. On the Hugging Face Space
there is no shell to run a backfill in, so this drives the admin HTTP
endpoints from here instead.

    python scripts/sync_live_citation_graph.py --limit 200

Credentials come from URAAS_ADMIN_USERNAME and URAAS_ADMIN_PASSWORD when
they are set, and from an interactive prompt otherwise. Nothing is read
from the command line, so the password never lands in a shell history.

The sync runs in a background thread on the server, so this polls
/api/citations/coverage and reports progress until the edge count stops
moving.
"""

import argparse
import getpass
import os
import sys
import time

import requests

DEFAULT_BASE_URL = "https://lordkiki-apa-uraas.hf.space"

# The Space sleeps when idle and takes roughly 30s to wake, and a bulk sync
# is many OpenAlex round trips behind one request.
WAKE_TIMEOUT_S = 120
POLL_INTERVAL_S = 20
# Stop once the edge count has been unchanged for this many polls. The
# server gives no completion signal, and "no new edges for a while" is the
# only honest end condition available.
QUIET_POLLS_TO_FINISH = 4


def credentials():
    username = os.getenv("URAAS_ADMIN_USERNAME")
    password = os.getenv("URAAS_ADMIN_PASSWORD")
    if not username:
        username = input("admin username: ").strip()
    if not password:
        password = getpass.getpass("admin password: ")
    return username, password


def coverage(session, base_url):
    r = session.get(f"{base_url}/api/citations/coverage", timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="records to sync in this run (1-1000, default 50)",
    )
    parser.add_argument(
        "--all-records",
        action="store_true",
        help="sync the whole corpus, not just Special Collections",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-sync records synced within the last 30 days",
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

    before = coverage(session, base_url)
    print(
        f"Before: {before['total_edges']} edges across "
        f"{before['records_with_inbound_edges']} cited "
        f"and {before['records_with_outbound_edges']} citing records"
    )

    r = session.post(
        f"{base_url}/api/admin/citations/sync-graph",
        json={
            "limit": args.limit,
            "sc_only": not args.all_records,
            "force": args.force,
        },
        timeout=60,
    )
    if r.status_code != 200:
        sys.exit(f"sync request rejected ({r.status_code}): {r.text[:200]}")
    print(f"Sync started: {r.json()}")

    last = before["total_edges"]
    quiet = 0
    while quiet < QUIET_POLLS_TO_FINISH:
        time.sleep(POLL_INTERVAL_S)
        try:
            now = coverage(session, base_url)
        except requests.RequestException as exc:
            print(f"  poll failed ({exc}), retrying")
            continue
        edges = now["total_edges"]
        if edges == last:
            quiet += 1
            print(f"  {edges} edges (unchanged, {quiet}/{QUIET_POLLS_TO_FINISH})")
        else:
            quiet = 0
            print(f"  {edges} edges (+{edges - last})")
        last = edges

    after = coverage(session, base_url)
    print()
    print(
        f"After: {after['total_edges']} edges across "
        f"{after['records_with_inbound_edges']} cited "
        f"and {after['records_with_outbound_edges']} citing records"
    )
    print(f"Added: {after['total_edges'] - before['total_edges']} edges")
    remaining = after["special_collections_eligible_for_sync"]
    print(
        f"{remaining} Special Collections records carry an identifier and are "
        "eligible; re-run with a larger --limit to continue."
    )


if __name__ == "__main__":
    main()
