import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import SessionLocal, Base, engine
from sqlalchemy import text


def inspect():
    session = SessionLocal()
    try:
        # Check if tables exist first
        tables = ["citations", "citation_metrics", "author_metrics"]
        for table in tables:
            try:
                res = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"Table '{table}' has {res} rows")
            except Exception as e:
                print(f"Table '{table}' error: {e}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    inspect()
