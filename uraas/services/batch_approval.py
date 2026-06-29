"""Batch approval orchestration for IR deposits.

Lifecycle
---------
pending_approval  ← batch created, approval email sent
   │
   ├─(approve link clicked)─→ approved  ─→ depositing ─→ completed
   │                                                    └─→ failed
   └─(reject link clicked) ─→ rejected

Security
--------
* Tokens are 32-byte cryptographically random values (URL-safe base64, ~43 chars).
* Tokens expire after APPROVAL_LINK_TTL_HOURS (default 48 h).
* Each token is single-use: once consumed (approved or rejected) its status
  changes and subsequent requests return 410 Gone.
"""

import json
import logging
import secrets
import threading
from datetime import datetime, timedelta

from uraas.config import config
from uraas.database import DepositBatch, Item, File, SessionLocal
from uraas.services.email_service import send_batch_approval_request

logger = logging.getLogger(__name__)

APPROVAL_LINK_TTL_HOURS = 48


# ── Public API ────────────────────────────────────────────────────────────────

def queue_batch(
    *,
    item_ids: list[int],
    collection_uuid: str,
    collection_name: str,
    approval_email: str,
    requested_by: str,
) -> dict:
    """Persist a pending batch and fire the approval email.

    Returns a result dict with status, batch_id, and email_sent flag.
    """
    if not item_ids:
        return {"status": "error", "message": "No item IDs provided"}

    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=APPROVAL_LINK_TTL_HOURS)

    db = SessionLocal()
    try:
        batch = DepositBatch(
            token=token,
            status="pending_approval",
            approval_email=approval_email,
            collection_uuid=collection_uuid,
            collection_name=collection_name,
            item_ids_json=json.dumps(item_ids),
            item_count=len(item_ids),
            requested_by=requested_by,
            expires_at=expires,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        batch_id = batch.id
    finally:
        db.close()

    approve_url = f"{config.DASHBOARD_BASE_URL}/api/ir/batch/{token}/approve"
    reject_url = f"{config.DASHBOARD_BASE_URL}/api/ir/batch/{token}/reject"

    email_sent = send_batch_approval_request(
        to_email=approval_email,
        approve_url=approve_url,
        reject_url=reject_url,
        batch_id=batch_id,
        item_count=len(item_ids),
        collection_name=collection_name,
        requested_by=requested_by,
        expires_hours=APPROVAL_LINK_TTL_HOURS,
    )

    return {
        "status": "queued",
        "batch_id": batch_id,
        "item_count": len(item_ids),
        "approval_email": approval_email,
        "email_sent": email_sent,
        "expires_at": expires.isoformat(),
        # Return the approve URL so an admin can action it directly from the
        # dashboard if SMTP is not yet configured.
        "approve_url": approve_url,
    }


def approve_batch(token: str) -> dict:
    """Validate token and kick off the deposit in a background thread.

    Returns a result dict suitable for rendering an HTML confirmation page.
    """
    db = SessionLocal()
    try:
        batch = db.query(DepositBatch).filter_by(token=token).first()
        if not batch:
            return {"status": "not_found", "message": "Approval link not found or already used."}
        if batch.status != "pending_approval":
            return {
                "status": "already_actioned",
                "message": f"This batch has already been {batch.status}.",
                "batch_status": batch.status,
                "batch_id": batch.id,
            }
        if batch.expires_at and datetime.utcnow() > batch.expires_at:
            batch.status = "rejected"
            batch.notes = "Approval link expired"
            batch.updated_at = datetime.utcnow()
            db.commit()
            return {"status": "expired", "message": "This approval link has expired."}

        batch.status = "approved"
        batch.approved_at = datetime.utcnow()
        batch.updated_at = datetime.utcnow()
        db.commit()
        batch_id = batch.id
    finally:
        db.close()

    # Start deposit in background so the HTTP response returns immediately
    t = threading.Thread(target=_run_deposit, args=(batch_id,), daemon=True)
    t.start()

    return {
        "status": "approved",
        "batch_id": batch_id,
        "message": (
            f"Batch #{batch_id} approved. Deposit is running in the background. "
            "Check the dashboard for progress."
        ),
    }


def reject_batch(token: str, reason: str = "") -> dict:
    """Mark the batch as rejected.  Called from the email rejection link."""
    db = SessionLocal()
    try:
        batch = db.query(DepositBatch).filter_by(token=token).first()
        if not batch:
            return {"status": "not_found", "message": "Rejection link not found or already used."}
        if batch.status != "pending_approval":
            return {
                "status": "already_actioned",
                "message": f"This batch has already been {batch.status}.",
                "batch_status": batch.status,
                "batch_id": batch.id,
            }
        batch.status = "rejected"
        batch.notes = reason or "Rejected via email link"
        batch.updated_at = datetime.utcnow()
        db.commit()
        return {
            "status": "rejected",
            "batch_id": batch.id,
            "message": f"Batch #{batch.id} has been rejected and will not be deposited.",
        }
    finally:
        db.close()


def get_batch(token: str) -> dict | None:
    """Return batch detail dict for a given token (admin status polling)."""
    db = SessionLocal()
    try:
        batch = db.query(DepositBatch).filter_by(token=token).first()
        return _batch_to_dict(batch) if batch else None
    finally:
        db.close()


def get_batches(limit: int = 50) -> list[dict]:
    """Return all batches most-recent-first for the admin panel."""
    db = SessionLocal()
    try:
        rows = (
            db.query(DepositBatch)
            .order_by(DepositBatch.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_batch_to_dict(b) for b in rows]
    finally:
        db.close()


# ── Internal deposit runner ───────────────────────────────────────────────────

def _run_deposit(batch_id: int):
    """Background thread: iterate over the batch items and deposit each one."""
    from uraas.services.ir_client import DSpaceClient, IRConnectionError

    db = SessionLocal()
    try:
        batch = db.query(DepositBatch).filter_by(id=batch_id).first()
        if not batch or batch.status != "approved":
            return

        batch.status = "depositing"
        batch.updated_at = datetime.utcnow()
        db.commit()

        item_ids: list[int] = json.loads(batch.item_ids_json or "[]")
        collection_uuid: str = batch.collection_uuid or ""
        deposit_log: list[dict] = []
        ok_count = 0
        fail_count = 0

        client = DSpaceClient()
        try:
            client.login()
        except IRConnectionError as exc:
            _mark_failed(db, batch, f"IR login failed: {exc}")
            return

        UNILAG_ROR = "https://ror.org/05rk03822"

        for item_id in item_ids:
            item = db.query(Item).filter_by(id=item_id).first()
            if not item:
                deposit_log.append({"item_id": item_id, "status": "error", "message": "Not found in local DB"})
                fail_count += 1
                continue

            # Only deposit papers affiliated with UNILAG — other institutions
            # will get their own IR integrations later.
            is_unilag = (item.ror == UNILAG_ROR) or (
                "university of lagos" in (item.institution or "").lower()
            )
            if not is_unilag:
                deposit_log.append({
                    "item_id": item_id,
                    "status": "skipped",
                    "message": f"Not a UNILAG paper (institution: {item.institution!r})",
                })
                continue

            # Resolve local PDF path if one exists
            pdf_path: str | None = None
            file_rec = db.query(File).filter_by(item_id=item_id).first()
            if file_rec and file_rec.file_path:
                import os
                candidate = file_rec.file_path
                if not os.path.isabs(candidate):
                    candidate = os.path.join(config.STORAGE_PATH, candidate)
                if os.path.exists(candidate):
                    pdf_path = candidate

            try:
                result = client.deposit_item(collection_uuid, item, pdf_path=pdf_path)
            except Exception as exc:
                result = {"status": "error", "message": str(exc)[:500]}

            result["item_id"] = item_id
            deposit_log.append(result)

            if result["status"] == "ok":
                ok_count += 1
            elif result["status"] == "duplicate":
                ok_count += 1  # not a failure — item is already in IR
            else:
                fail_count += 1

            # Persist progress periodically
            if len(deposit_log) % 10 == 0:
                batch.deposited_count = ok_count
                batch.failed_count = fail_count
                batch.deposit_log = json.dumps(deposit_log)
                batch.updated_at = datetime.utcnow()
                db.commit()

        # Final state
        batch.deposited_count = ok_count
        batch.failed_count = fail_count
        batch.deposit_log = json.dumps(deposit_log)
        batch.status = "completed" if fail_count == 0 else "failed"
        batch.completed_at = datetime.utcnow()
        batch.updated_at = datetime.utcnow()
        if fail_count:
            batch.notes = f"{fail_count} item(s) failed to deposit — see deposit_log for details"
        db.commit()
        logger.info(
            "Batch %s deposit complete: %d ok, %d failed", batch_id, ok_count, fail_count
        )

    except Exception as exc:
        logger.exception("Unexpected error in deposit batch %s: %s", batch_id, exc)
        try:
            _mark_failed(db, db.query(DepositBatch).filter_by(id=batch_id).first(), str(exc))
        except Exception:
            pass
    finally:
        db.close()


def _mark_failed(db, batch, reason: str):
    if batch:
        batch.status = "failed"
        batch.notes = reason
        batch.updated_at = datetime.utcnow()
        db.commit()
    logger.error("Deposit batch failed: %s", reason)


# ── Serialisation helper ──────────────────────────────────────────────────────

def _batch_to_dict(batch: DepositBatch) -> dict:
    return {
        "id": batch.id,
        "status": batch.status,
        "approval_email": batch.approval_email,
        "collection_uuid": batch.collection_uuid,
        "collection_name": batch.collection_name,
        "item_count": batch.item_count,
        "deposited_count": batch.deposited_count,
        "failed_count": batch.failed_count,
        "requested_by": batch.requested_by,
        "notes": batch.notes,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
        "expires_at": batch.expires_at.isoformat() if batch.expires_at else None,
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "deposit_log": json.loads(batch.deposit_log or "[]"),
    }
