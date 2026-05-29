import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uraas.database import SessionLocal, Item
from sqlalchemy import func

print("DB connection ok", flush=True)

session = SessionLocal()
try:
    print("Querying year count...", flush=True)
    # Using the same logic as db_year for SQLite
    year_col = func.strftime("%Y", Item.publication_date)
    res = (
        session.query(year_col, func.count(Item.id))
        .filter(Item.publication_date.isnot(None))
        .group_by(year_col)
        .all()
    )
    print("Result:", res, flush=True)
except Exception as e:
    print("Error:", e, flush=True)
finally:
    session.close()
