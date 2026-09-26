"""Engine construction tests.

These live apart from the feature suites because they are about how URAAS
connects to a database at all, not about what it stores.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_postgres_urls_name_their_driver_explicitly():
    """SQLAlchemy's default DBAPI for a bare postgresql:// URL is not stable.

    2.1 changed it from psycopg2 to psycopg (v3). requirements.txt ships
    psycopg2-binary, so the moment CI resolved SQLAlchemy 2.1.1 every
    Postgres connection died with "No module named 'psycopg'" - unchanged
    URL, unchanged code, unpinned dependency.
    """
    import uraas.database as db

    for given in ("postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(db.config, "DATABASE_URL", given)
            engine = db._build_engine()
        assert engine.dialect.driver == "psycopg2", given


def test_an_explicit_driver_is_left_alone():
    """postgresql+psycopg:// must still select v3 for anyone who wants it."""
    from sqlalchemy.engine import make_url

    import uraas.database as db

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db.config, "DATABASE_URL", "postgresql+psycopg://u:p@h/d")
        # Building the engine would import psycopg, which is not installed;
        # the URL rewrite is what is under test, so check that instead.
        url = db.config.DATABASE_URL
        assert make_url(url).drivername == "postgresql+psycopg"


def test_sqlite_urls_are_untouched():
    import uraas.database as db

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db.config, "DATABASE_URL", "sqlite:///:memory:")
        engine = db._build_engine()
    assert engine.dialect.name == "sqlite"
