"""SMTP email service for batch approval notifications.

Sends a styled HTML email to the approver with one-click Approve / Reject
links.  Requires SMTP_HOST, SMTP_USER, SMTP_PASSWORD in the environment.
If SMTP is not configured the call logs a warning and returns False so the
rest of the deposit flow degrades gracefully (the admin can still approve
via the dashboard).
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

from uraas.config import config

logger = logging.getLogger(__name__)


def _is_smtp_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD)


def send_batch_approval_request(
    *,
    to_email: str,
    approve_url: str,
    reject_url: str,
    batch_id: int,
    item_count: int,
    collection_name: str,
    requested_by: str,
    expires_hours: int = 48,
) -> bool:
    """Send the approval-request email and return True on success."""
    if not _is_smtp_configured():
        logger.warning(
            "SMTP not configured — skipping approval email for batch %s. "
            "Admin can approve at: %s",
            batch_id,
            approve_url,
        )
        return False

    subject = f"[URAAS] Approve IR deposit — Batch #{batch_id} ({item_count} papers)"
    html = _build_html(
        batch_id=batch_id,
        item_count=item_count,
        collection_name=collection_name,
        requested_by=requested_by,
        approve_url=approve_url,
        reject_url=reject_url,
        expires_hours=expires_hours,
    )
    plain = _build_plain(
        batch_id=batch_id,
        item_count=item_count,
        collection_name=collection_name,
        requested_by=requested_by,
        approve_url=approve_url,
        reject_url=reject_url,
        expires_hours=expires_hours,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if config.SMTP_USE_TLS:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30)

        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        # envelope MAIL FROM must be bare address, not "Name <addr>"
        envelope_from = parseaddr(config.SMTP_FROM)[1] or config.SMTP_USER
        server.sendmail(envelope_from, [to_email], msg.as_bytes())
        server.quit()
        logger.info("Approval email sent for batch %s → %s", batch_id, to_email)
        return True
    except Exception as exc:
        logger.error("Failed to send approval email for batch %s: %s", batch_id, exc)
        return False


# ── Email templates ───────────────────────────────────────────────────────────


def _build_html(
    batch_id,
    item_count,
    collection_name,
    requested_by,
    approve_url,
    reject_url,
    expires_hours,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:40px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
      <!-- Header -->
      <tr><td style="background:#1a3a5c;padding:28px 32px;">
        <p style="margin:0;font-size:11px;color:#7eb3d4;letter-spacing:2px;text-transform:uppercase;">University of Lagos</p>
        <h1 style="margin:6px 0 0;font-size:22px;color:#ffffff;font-weight:700;">URAAS — IR Deposit Approval</h1>
      </td></tr>
      <!-- Body -->
      <tr><td style="padding:32px;">
        <p style="margin:0 0 16px;font-size:15px;color:#333333;line-height:1.6;">
          <strong>{requested_by}</strong> has queued a batch of research papers
          for deposit into the UNILAG Institutional Repository.
          <strong>Your approval is required before any data is sent to the live IR.</strong>
        </p>
        <!-- Batch details table -->
        <table width="100%" cellpadding="10" cellspacing="0"
               style="background:#f8f9fc;border:1px solid #e0e6ef;border-radius:6px;margin:20px 0;font-size:14px;">
          <tr>
            <td style="color:#555;width:160px;">Batch ID</td>
            <td style="color:#1a3a5c;font-weight:700;">#{batch_id}</td>
          </tr>
          <tr style="border-top:1px solid #e0e6ef;">
            <td style="color:#555;">Papers to deposit</td>
            <td style="color:#1a3a5c;font-weight:700;">{item_count}</td>
          </tr>
          <tr style="border-top:1px solid #e0e6ef;">
            <td style="color:#555;">Target collection</td>
            <td style="color:#1a3a5c;font-weight:700;">{collection_name or 'Not specified'}</td>
          </tr>
          <tr style="border-top:1px solid #e0e6ef;">
            <td style="color:#555;">Requested by</td>
            <td style="color:#1a3a5c;font-weight:700;">{requested_by}</td>
          </tr>
          <tr style="border-top:1px solid #e0e6ef;">
            <td style="color:#555;">Link expires</td>
            <td style="color:#c0392b;font-weight:700;">in {expires_hours} hours</td>
          </tr>
        </table>
        <p style="margin:0 0 24px;font-size:14px;color:#555555;line-height:1.6;">
          Clicking <strong>Approve</strong> will immediately begin depositing all
          {item_count} paper(s) to the live DSpace IR at
          <code style="background:#f0f0f0;padding:2px 5px;border-radius:3px;">api-ir.unilag.edu.ng</code>.
          This action cannot be undone for items that are already deposited.
        </p>
        <!-- CTA buttons -->
        <table cellpadding="0" cellspacing="0" style="margin:0 auto 24px;">
          <tr>
            <td style="padding-right:12px;">
              <a href="{approve_url}"
                 style="display:inline-block;padding:14px 32px;background:#1a7a4a;color:#ffffff;
                        text-decoration:none;border-radius:6px;font-size:16px;font-weight:700;">
                ✓ &nbsp;Approve Deposit
              </a>
            </td>
            <td>
              <a href="{reject_url}"
                 style="display:inline-block;padding:14px 32px;background:#c0392b;color:#ffffff;
                        text-decoration:none;border-radius:6px;font-size:16px;font-weight:700;">
                ✗ &nbsp;Reject Batch
              </a>
            </td>
          </tr>
        </table>
        <p style="font-size:12px;color:#888888;margin:0;line-height:1.6;">
          If the buttons do not work, copy these URLs into your browser:<br>
          <strong>Approve:</strong> {approve_url}<br>
          <strong>Reject:</strong> {reject_url}
        </p>
      </td></tr>
      <!-- Footer -->
      <tr><td style="background:#f0f4f8;padding:16px 32px;font-size:11px;color:#aaaaaa;text-align:center;">
        URAAS &mdash; APA Intelligence &amp; Analytics Platform &nbsp;|&nbsp; University of Lagos<br>
        This is an automated message. Do not reply.
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _build_plain(
    batch_id,
    item_count,
    collection_name,
    requested_by,
    approve_url,
    reject_url,
    expires_hours,
) -> str:
    return f"""URAAS — IR Deposit Approval Request
University of Lagos Institutional Repository
=============================================

{requested_by} has queued a deposit batch.

  Batch ID        : #{batch_id}
  Papers          : {item_count}
  Target collection: {collection_name or 'Not specified'}
  Requested by    : {requested_by}
  Link expires    : in {expires_hours} hours

ACTION REQUIRED
---------------

APPROVE (sends papers to the live IR):
{approve_url}

REJECT (cancels the batch):
{reject_url}

--
URAAS — APA Intelligence & Analytics Platform
University of Lagos
This is an automated message. Do not reply.
"""
