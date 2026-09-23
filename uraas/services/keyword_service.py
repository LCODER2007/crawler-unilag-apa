"""
Keyword Service
Per-record keyword access, backfill, and keyword-driven discovery.

The corpus-wide keyword cloud already lived in the analytics engine, but
there was nothing serving keywords for a *single* record: Item.ai_keywords is
written once at insert time by the ingestion pipeline and never touched
again, so any record that predates keyword extraction (or whose title and
abstract arrived empty and were filled in later) stays blank forever. This
module is the read/repair layer over that column, plus the two lookups a
partner integration actually needs: which records share a record's keywords,
and which records carry a given keyword.
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy import func, or_

from uraas.database import Item, SessionLocal
from uraas.services.sc_engine import SC_FILTER
from uraas.utils.ai_classifier import extract_keywords

logger = logging.getLogger(__name__)

# Keywords are stored as a single comma-separated string on the item. The
# pipeline writes them already normalised; older rows and hand-edited ones
# are not, so every read goes through _split().
SEPARATOR = ", "

# extract_keywords() is corpus-aware and returns up to top_n terms ranked by
# TF-IDF. Per record we want a tight, human-readable set, not the long tail.
PER_ITEM_TOP_N = 15


def _split(raw: Optional[str]) -> List[str]:
    """Parse the stored comma-separated column into a clean keyword list."""
    if not raw:
        return []
    seen = set()
    out = []
    for part in raw.split(","):
        kw = " ".join(part.split()).strip(" .;:-")
        if not kw:
            continue
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(kw)
    return out


def _extract_for_item(item: Item, top_n: int = PER_ITEM_TOP_N) -> List[str]:
    """Run extraction over one record's own text.

    No corpus is passed: extract_keywords() falls back to a log-frequency
    proxy for IDF, which is the right trade for a single record. The
    corpus-level ranking is what get_keyword_cloud() is for.
    """
    try:
        results = extract_keywords(item.title or "", item.abstract or "", top_n=top_n)
    except Exception as exc:
        logger.error("keyword extraction failed for item %s: %s", item.id, exc)
        return []
    return [r["word"] for r in results if r.get("word")]


def get_item_keywords(item_id: int, extract_if_missing: bool = True) -> Dict:
    """Keywords for one record.

    Falls back to extracting from title and abstract when the stored column
    is empty, and persists what it extracts so the next read is a plain
    column fetch. `source` tells the caller which path produced the answer.
    """
    session = SessionLocal()
    try:
        item = session.query(Item).filter_by(id=item_id).first()
        if not item:
            return {"item_id": item_id, "keywords": [], "source": "not_found"}

        stored = _split(item.ai_keywords)
        if stored:
            return {
                "item_id": item_id,
                "keywords": stored,
                "subjects": _split(item.dc_subject),
                "source": "stored",
            }

        if not extract_if_missing:
            return {
                "item_id": item_id,
                "keywords": [],
                "subjects": _split(item.dc_subject),
                "source": "empty",
            }

        extracted = _extract_for_item(item)
        subjects = _split(item.dc_subject)
        if extracted:
            item.ai_keywords = SEPARATOR.join(extracted)
            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.error("could not persist keywords for item %s: %s", item_id, exc)
        return {
            "item_id": item_id,
            "keywords": extracted,
            "subjects": subjects,
            "source": "extracted",
        }
    finally:
        session.close()


def backfill_keywords(limit: int = 500, force: bool = False) -> Dict:
    """Fill ai_keywords for records that have none.

    `force` re-extracts records that already have keywords, which is only
    worth doing after a change to the extractor itself.
    """
    session = SessionLocal()
    stats = {"scanned": 0, "updated": 0, "no_text": 0, "skipped": 0}
    try:
        q = session.query(Item)
        if not force:
            q = q.filter(or_(Item.ai_keywords.is_(None), Item.ai_keywords == ""))
        items = q.limit(limit).all()

        for item in items:
            stats["scanned"] += 1
            if not (item.title or item.abstract):
                stats["no_text"] += 1
                continue
            words = _extract_for_item(item)
            if not words:
                stats["skipped"] += 1
                continue
            item.ai_keywords = SEPARATOR.join(words)
            stats["updated"] += 1

        if stats["updated"]:
            session.commit()
        logger.info("keyword backfill: %s", stats)
        return stats
    except Exception as exc:
        session.rollback()
        logger.error("keyword backfill failed: %s", exc)
        stats["error"] = str(exc)
        return stats
    finally:
        session.close()


def search_by_keyword(
    keyword: str, limit: int = 50, sc_only: bool = False
) -> List[Dict]:
    """Records carrying a keyword, matched against ai_keywords and dc_subject."""
    kw = (keyword or "").strip()
    if not kw:
        return []

    session = SessionLocal()
    try:
        pattern = f"%{kw}%"
        q = session.query(Item).filter(
            or_(Item.ai_keywords.ilike(pattern), Item.dc_subject.ilike(pattern))
        )
        if sc_only:
            q = q.filter(SC_FILTER)
        rows = q.limit(limit).all()

        low = kw.lower()
        out = []
        for item in rows:
            words = _split(item.ai_keywords)
            # ilike matched anywhere in the string, including the middle of a
            # longer term. Report whether the keyword is a term in its own
            # right so the caller can tell an exact hit from a substring one.
            exact = any(w.lower() == low for w in words)
            out.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "doi": item.doi or "",
                    "year": (
                        item.publication_date.year if item.publication_date else None
                    ),
                    "keywords": words[:10],
                    "exact_match": exact,
                }
            )
        out.sort(key=lambda r: (not r["exact_match"], -(r["year"] or 0)))
        return out
    except Exception as exc:
        logger.error("search_by_keyword(%s): %s", kw, exc)
        return []
    finally:
        session.close()


def related_by_keywords(item_id: int, limit: int = 10) -> List[Dict]:
    """Records sharing the most keywords with this one.

    Deliberately a keyword overlap, not a citation-graph neighbourhood - the
    two answer different questions, and the citation graph is served by
    uraas.services.citation_tracker. Scored by Jaccard overlap so a record
    carrying 40 keywords cannot outrank a tight thematic match on volume
    alone.
    """
    session = SessionLocal()
    try:
        item = session.query(Item).filter_by(id=item_id).first()
        if not item:
            return []
        source_words = {w.lower() for w in _split(item.ai_keywords)}
        if not source_words:
            return []

        # Narrow the scan to records sharing at least one keyword rather than
        # loading the whole table. The OR of ILIKEs is a scan either way, but
        # it is one the database does rather than one Python does over every
        # row in the corpus.
        clauses = [Item.ai_keywords.ilike(f"%{w}%") for w in list(source_words)[:20]]
        candidates = (
            session.query(Item)
            .filter(Item.id != item_id, Item.ai_keywords.isnot(None), or_(*clauses))
            .limit(500)
            .all()
        )

        scored = []
        for cand in candidates:
            words = {w.lower() for w in _split(cand.ai_keywords)}
            if not words:
                continue
            shared = source_words & words
            if not shared:
                continue
            score = len(shared) / len(source_words | words)
            scored.append(
                {
                    "id": cand.id,
                    "title": cand.title,
                    "doi": cand.doi or "",
                    "year": (
                        cand.publication_date.year if cand.publication_date else None
                    ),
                    "shared_keywords": sorted(shared),
                    "overlap_score": round(score, 4),
                }
            )
        scored.sort(key=lambda r: -r["overlap_score"])
        return scored[:limit]
    except Exception as exc:
        logger.error("related_by_keywords(%s): %s", item_id, exc)
        return []
    finally:
        session.close()


def keyword_coverage() -> Dict:
    """How much of the corpus actually has keywords - the number that says
    whether a backfill is still outstanding."""
    session = SessionLocal()
    try:
        total = session.query(func.count(Item.id)).scalar() or 0
        with_kw = (
            session.query(func.count(Item.id))
            .filter(Item.ai_keywords.isnot(None), Item.ai_keywords != "")
            .scalar()
            or 0
        )
        sc_total = session.query(func.count(Item.id)).filter(SC_FILTER).scalar() or 0
        sc_with_kw = (
            session.query(func.count(Item.id))
            .filter(SC_FILTER, Item.ai_keywords.isnot(None), Item.ai_keywords != "")
            .scalar()
            or 0
        )
        return {
            "total_items": total,
            "items_with_keywords": with_kw,
            "coverage_pct": round(with_kw / total * 100, 1) if total else 0.0,
            "special_collections_items": sc_total,
            "special_collections_with_keywords": sc_with_kw,
        }
    finally:
        session.close()
