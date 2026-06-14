"""
Lightweight authentication for the URAAS dashboard.

Zero external auth dependencies: Flask `session` cookies (signed with
DASHBOARD_SECRET_KEY) + Werkzeug password hashing. Two roles:

    admin  — full control: crawler, mutations, bulk exports, staff directory,
             and download of any stored file regardless of rights.
    viewer — read access to the dashboard and analytics; may download only
             open-access files.

Credentials come from the environment (see uraas.config.Config). Passwords are
stored as Werkzeug hashes, never plaintext. This is an interim layer; the
deployment plan replaces/augments it with institutional SSO (Shibboleth/LDAP).
"""

import functools

from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

from uraas.config import config

ADMIN = "admin"
VIEWER = "viewer"


def check_credentials(username: str, password: str):
    """Return the role string for valid credentials, else None.

    Constant-ish: always runs a hash comparison against the matching user's
    stored hash. Unknown users / empty hashes return None.
    """
    if not username or not password:
        return None
    candidates = (
        (config.ADMIN_USERNAME, config.ADMIN_PASSWORD_HASH, ADMIN),
        (config.VIEWER_USERNAME, config.VIEWER_PASSWORD_HASH, VIEWER),
    )
    for user, pw_hash, role in candidates:
        if username == user and pw_hash and check_password_hash(pw_hash, password):
            return role
    return None


def current_role():
    """Role of the logged-in user, or None if unauthenticated."""
    return session.get("role")


def _wants_json() -> bool:
    """True for API/XHR requests, which should get a 401 rather than a redirect."""
    return request.path.startswith("/api/") or request.accept_mimetypes.best == (
        "application/json"
    )


def login_required(view):
    """Require any authenticated user (viewer or admin)."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not current_role():
            if _wants_json():
                return jsonify({"status": "error", "message": "Authentication required"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Require an authenticated admin. 401 if anonymous, 403 if a viewer."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        role = current_role()
        if not role:
            if _wants_json():
                return jsonify({"status": "error", "message": "Authentication required"}), 401
            return redirect(url_for("login", next=request.path))
        if role != ADMIN:
            return jsonify({"status": "error", "message": "Administrator access required"}), 403
        return view(*args, **kwargs)

    return wrapped


def clamped_int(name: str, default: int, lo: int, hi: int) -> int:
    """Read an int query param, defaulting and clamping to [lo, hi].

    Never raises on bad input (returns default), so endpoints can't be DoS'd
    with huge limits or 500'd with non-numeric values.
    """
    raw = request.args.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    return max(lo, min(value, hi))
