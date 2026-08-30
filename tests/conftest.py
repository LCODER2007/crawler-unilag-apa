"""Shared pytest fixtures.

Sets admin/viewer credentials as env vars BEFORE any uraas module is
imported — uraas.config.Config reads them at class-definition time via
os.getenv(), so setting them later (e.g. inside a fixture) is too late.
This is why test_api.py's endpoint tests all failed with 401 once the
session-auth gate was added to the dashboard: the test client was never
able to log in at all.
"""

import os

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("VIEWER_USERNAME", "viewer")

from werkzeug.security import generate_password_hash  # noqa: E402

TEST_ADMIN_PASSWORD = "test-admin-password"
TEST_VIEWER_PASSWORD = "test-viewer-password"

os.environ.setdefault(
    "ADMIN_PASSWORD_HASH", generate_password_hash(TEST_ADMIN_PASSWORD)
)
os.environ.setdefault(
    "VIEWER_PASSWORD_HASH", generate_password_hash(TEST_VIEWER_PASSWORD)
)
os.environ.setdefault("DASHBOARD_SECRET_KEY", "test-suite-secret-key")

import pytest  # noqa: E402

from uraas.dashboard.app import app as flask_app  # noqa: E402
from uraas.dashboard.app import limiter as _limiter  # noqa: E402

flask_app.config["TESTING"] = True
# The login route is deliberately rate-limited (10/min) against real brute-
# force attempts — a real, wanted production behavior, not something the
# test suite should trip over just because admin_client logs in fresh once
# per test. flask_app.config["RATELIMIT_ENABLED"] = False alone did not take
# effect (Flask-Limiter reads its own .enabled attribute, set at
# construction, not a live app.config lookup) — disable the limiter object
# directly instead.
_limiter.enabled = False


# function-scoped, not module-scoped: Flask's request-context stack is
# shared per-thread across every test_client() instance of the same app, so
# having client/admin_client/viewer_client all "open" simultaneously as
# module fixtures caused a real, reproducible
# "AssertionError: Popped wrong request context" whenever tests using
# different fixtures interleaved. A fresh client per test avoids any overlap
# — login is cheap enough that the extra round-trip per test doesn't matter.


@pytest.fixture
def client():
    """An unauthenticated test client — for testing the public surface
    (login, health, 401 behavior) itself."""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def admin_client():
    """A test client already logged in as admin."""
    with flask_app.test_client() as c:
        r = c.post(
            "/login", data={"username": "admin", "password": TEST_ADMIN_PASSWORD}
        )
        assert (
            r.status_code == 302
        ), "admin login must succeed for the fixture to be usable"
        yield c


@pytest.fixture
def viewer_client():
    """A test client already logged in as viewer (read-only role)."""
    with flask_app.test_client() as c:
        r = c.post(
            "/login", data={"username": "viewer", "password": TEST_VIEWER_PASSWORD}
        )
        assert (
            r.status_code == 302
        ), "viewer login must succeed for the fixture to be usable"
        yield c
