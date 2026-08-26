"""Manage API keys for external partner access to the URAAS dashboard API
(e.g. Africa PID Alliance / DOCiD reading papers/analytics endpoints
server-to-server, instead of using the browser session-cookie login).

The plaintext key is shown exactly once, at creation — it is never stored;
only its SHA-256 hash is, so a stolen database dump can't be used to
authenticate as a partner. If a key is lost, revoke it and create a new one.

Usage:
    python scripts/manage_api_keys.py create --name "Africa PID Alliance / DOCiD"
    python scripts/manage_api_keys.py list
    python scripts/manage_api_keys.py revoke --prefix uraas_live_AbCd
"""

import argparse
import hashlib
import os
import secrets
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import ApiKey, SessionLocal

_PREFIX = "uraas_live_"


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def cmd_create(args):
    raw = _PREFIX + secrets.token_urlsafe(32)
    session = SessionLocal()
    try:
        row = ApiKey(
            name=args.name,
            key_hash=_hash(raw),
            key_prefix=raw[: len(_PREFIX) + 8],
            scope="read",
            created_by=args.created_by or "cli",
        )
        session.add(row)
        session.commit()
        print("Created API key — this is the ONLY time the full value is shown:\n")
        print(f"    {raw}\n")
        print(f"Name:   {row.name}")
        print(f"Prefix: {row.key_prefix}  (safe to log/reference later)")
        print(f"Scope:  {row.scope}")
        print("\nGive the partner this header format:")
        print(f'    X-API-Key: {raw}')
    finally:
        session.close()


def cmd_list(args):
    session = SessionLocal()
    try:
        rows = session.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
        if not rows:
            print("No API keys yet.")
            return
        for r in rows:
            status = "REVOKED" if r.revoked else "active"
            last_used = r.last_used_at.isoformat() if r.last_used_at else "never"
            print(f"[{r.id}] {r.key_prefix}...  {r.name!r}  scope={r.scope}  "
                  f"status={status}  created={r.created_at}  last_used={last_used}")
    finally:
        session.close()


def cmd_revoke(args):
    session = SessionLocal()
    try:
        q = session.query(ApiKey)
        row = None
        if args.id:
            row = q.filter(ApiKey.id == args.id).first()
        elif args.prefix:
            row = q.filter(ApiKey.key_prefix == args.prefix).first()
        if not row:
            print("No matching key found.")
            return
        row.revoked = True
        row.revoked_at = datetime.utcnow()
        session.commit()
        print(f"Revoked key [{row.id}] {row.key_prefix}... ({row.name!r})")
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Issue a new partner API key")
    p_create.add_argument("--name", required=True, help="Partner label, e.g. 'Africa PID Alliance / DOCiD'")
    p_create.add_argument("--created-by", default=None)
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="List all keys (never shows the full value)")
    p_list.set_defaults(func=cmd_list)

    p_revoke = sub.add_parser("revoke", help="Revoke a key")
    p_revoke.add_argument("--id", type=int, default=None)
    p_revoke.add_argument("--prefix", default=None)
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    if args.command == "revoke" and not (args.id or args.prefix):
        parser.error("revoke requires --id or --prefix")
    args.func(args)


if __name__ == "__main__":
    main()
