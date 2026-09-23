"""
Citation Tracking Service
Fetches citation counts and citation graphs from OpenAlex and Crossref.
Calculates h-index and other bibliometric indicators.
Scoped to Special Collections items (SC_FILTER) - mirrors the analytics engine.
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

import requests
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from uraas.config.african_countries import AFRICAN_ISO2
from uraas.database import Author, Base, Item, SessionLocal
from uraas.services.sc_engine import SC_FILTER

logger = logging.getLogger(__name__)


# -- New Database Models for Citations ----------------------------------------


class Citation(Base):
    """One directed citation edge: citing work -> cited work.

    Only one end of an edge is normally a record URAAS holds. The corpus is
    institution-scoped, so the works citing a UNILAG paper are overwhelmingly
    *not* UNILAG papers, and neither are the works it references. The
    original version of this table only stored an edge when both ends
    resolved to a local Item, which is why it stayed empty: it was recording
    the intersection of the graph with itself.

    So the foreign keys are nullable and carry external identity alongside
    them. `citing_item_id` / `cited_item_id` are filled opportunistically
    when the other end does happen to be in the corpus; `*_doi`,
    `*_openalex_id`, `*_title` and `*_year` always describe the edge
    regardless.
    """

    __tablename__ = "citations"

    id = Column(Integer, primary_key=True)
    citing_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"))
    cited_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"))
    citation_date = Column(DateTime)
    source = Column(String(50))  # 'openalex', 'crossref', 'manual'

    # External identity of the citing work (set when it is not a local Item)
    citing_doi = Column(String(255), index=True)
    citing_openalex_id = Column(String(64))
    citing_title = Column(Text)
    citing_year = Column(Integer)

    # External identity of the cited work (set when it is not a local Item)
    cited_doi = Column(String(255), index=True)
    cited_openalex_id = Column(String(64))
    cited_title = Column(Text)
    cited_year = Column(Integer)

    # Deterministic hash of (citing identity, cited identity). SQLite cannot
    # add a UNIQUE constraint through ALTER TABLE, and this table already
    # exists on deployed databases, so de-duplication is a lookup on this
    # column rather than a constraint the database enforces.
    edge_key = Column(String(40), index=True)

    citing_item = relationship("Item", foreign_keys=[citing_item_id])
    cited_item = relationship("Item", foreign_keys=[cited_item_id])


class CitationMetrics(Base):
    """Cached citation metrics for papers."""

    __tablename__ = "citation_metrics"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"), unique=True)
    citation_count = Column(Integer, default=0)
    h_index = Column(Integer, default=0)
    i10_index = Column(Integer, default=0)  # papers with 10+ citations
    last_updated = Column(DateTime, default=datetime.utcnow)

    item = relationship("Item")


class AuthorMetrics(Base):
    """Cached bibliometric indicators for authors."""

    __tablename__ = "author_metrics"

    id = Column(Integer, primary_key=True)
    author_id = Column(
        Integer, ForeignKey("authors.id", ondelete="CASCADE"), unique=True
    )
    total_citations = Column(Integer, default=0)
    h_index = Column(Integer, default=0)
    i10_index = Column(Integer, default=0)
    total_papers = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)

    author = relationship("Author")


# -- Identity helpers ----------------------------------------------------------

USER_AGENT = "URAAS/1.0 (mailto:library@unilag.edu.ng)"


def normalise_doi(value: Optional[str]) -> str:
    """Bare lower-case DOI, however OpenAlex or Crossref happened to spell it."""
    if not value:
        return ""
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.strip()


def short_openalex_id(value: Optional[str]) -> str:
    """'W2741809807' from either the bare id or the full API URL."""
    if not value:
        return ""
    return value.rstrip("/").rsplit("/", 1)[-1].strip()


def edge_key(citing: Dict, cited: Dict) -> str:
    """Stable identity for one directed edge.

    Prefers DOI, then OpenAlex id, then the local item id, then a normalised
    title - so the same edge learned from two different lookups collapses to
    one row instead of accumulating duplicates on every re-run.
    """

    def side(part: Dict) -> str:
        doi = normalise_doi(part.get("doi"))
        if doi:
            return f"doi:{doi}"
        oa = short_openalex_id(part.get("openalex_id"))
        if oa:
            return f"oa:{oa}"
        if part.get("item_id"):
            return f"item:{part['item_id']}"
        title = " ".join((part.get("title") or "").lower().split())
        return f"title:{title}" if title else "unknown"

    raw = f"{side(citing)}->{side(cited)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# -- Citation Fetching Service -------------------------------------------------


class CitationTracker:
    """Fetches and tracks citations from external APIs."""

    OPENALEX_API = "https://api.openalex.org/works"
    CROSSREF_API = "https://api.crossref.org/works"

    # OpenAlex allows 200 per page. A highly cited paper can have thousands
    # of citing works; storing all of them for every record would dwarf the
    # corpus itself, so inbound edges are capped and the true total stays on
    # Item.cited_by_count.
    MAX_CITING_EDGES = 200
    MAX_REFERENCE_EDGES = 200

    @staticmethod
    def fetch_citations_openalex(doi: str) -> Optional[Dict]:
        """
        Fetch citation data from OpenAlex.

        Returns:
            {
                'citation_count': int,
                'cited_by_api_url': str,
                'citations': [{'doi': str, 'title': str, 'year': int}, ...]
            }
        """
        try:
            url = f"{CitationTracker.OPENALEX_API}/doi:{doi}"
            headers = {"User-Agent": "URAAS/1.0 (mailto:library@unilag.edu.ng)"}
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()
            citation_count = data.get("cited_by_count", 0)
            cited_by_url = data.get("cited_by_api_url")

            # Fetch citing papers
            citations = []
            if cited_by_url and citation_count > 0:
                cite_response = requests.get(cited_by_url, headers=headers, timeout=10)
                if cite_response.status_code == 200:
                    cite_data = cite_response.json()
                    for result in cite_data.get("results", [])[:100]:  # Limit to 100
                        citations.append(
                            {
                                "doi": result.get("doi", "").replace(
                                    "https://doi.org/", ""
                                ),
                                "title": result.get("title", ""),
                                "year": result.get("publication_year"),
                                "authors": [
                                    a.get("author", {}).get("display_name")
                                    for a in result.get("authorships", [])[:3]
                                ],
                            }
                        )

            return {
                "citation_count": citation_count,
                "cited_by_api_url": cited_by_url,
                "citations": citations,
            }

        except Exception as e:
            logger.error(f"OpenAlex citation fetch failed for {doi}: {e}")
            return None

    @staticmethod
    def fetch_citations_crossref(doi: str) -> Optional[int]:
        """Fetch citation count from Crossref (simpler, just count)."""
        try:
            url = f"{CitationTracker.CROSSREF_API}/{doi}"
            headers = {"User-Agent": "URAAS/1.0 (mailto:library@unilag.edu.ng)"}
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()
            return data.get("message", {}).get("is-referenced-by-count", 0)

        except Exception as e:
            logger.error(f"Crossref citation fetch failed for {doi}: {e}")
            return None

    # -- Citation graph (edge list) -------------------------------------------

    @staticmethod
    def _get(url: str, timeout: int = 20) -> Optional[Dict]:
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code != 200:
                logger.debug("OpenAlex %s -> %s", url, r.status_code)
                return None
            return r.json()
        except Exception as e:
            logger.error(f"OpenAlex request failed ({url}): {e}")
            return None

    @staticmethod
    def _work_summary(work: Dict) -> Dict:
        """Flatten one OpenAlex work into the fields an edge needs."""
        return {
            "openalex_id": short_openalex_id(work.get("id")),
            "doi": normalise_doi(work.get("doi")),
            "title": work.get("title") or work.get("display_name") or "",
            "year": work.get("publication_year"),
        }

    @staticmethod
    def fetch_work(doi: str = "", openalex_id: str = "") -> Optional[Dict]:
        """One OpenAlex work, looked up by OpenAlex id or DOI."""
        oa = short_openalex_id(openalex_id)
        if oa:
            return CitationTracker._get(f"{CitationTracker.OPENALEX_API}/{oa}")
        doi_n = normalise_doi(doi)
        if doi_n:
            return CitationTracker._get(f"{CitationTracker.OPENALEX_API}/doi:{doi_n}")
        return None

    @staticmethod
    def fetch_citing_works(openalex_id: str, limit: int = 200) -> List[Dict]:
        """Works that cite the given work (inbound edges), newest first.

        Pages with a cursor rather than `page=`: OpenAlex caps offset paging
        at 10 000 results and a well-cited work can exceed it.
        """
        oa = short_openalex_id(openalex_id)
        if not oa:
            return []

        out: List[Dict] = []
        cursor = "*"
        while cursor and len(out) < limit:
            per_page = min(200, limit - len(out))
            url = (
                f"{CitationTracker.OPENALEX_API}?filter=cites:{oa}"
                f"&per_page={per_page}&cursor={cursor}"
                f"&select=id,doi,title,publication_year"
            )
            data = CitationTracker._get(url)
            if not data:
                break
            results = data.get("results", [])
            if not results:
                break
            out.extend(CitationTracker._work_summary(w) for w in results)
            cursor = (data.get("meta") or {}).get("next_cursor")
        return out[:limit]

    @staticmethod
    def fetch_referenced_works(
        referenced_ids: Iterable[str], limit: int = 200
    ) -> List[Dict]:
        """Resolve a work's `referenced_works` ids into titles, DOIs and years.

        The work record gives only bare OpenAlex ids. Resolving them costs one
        request per 50 ids via the `openalex_id:A|B|C` filter, not one per
        reference.
        """
        ids = [short_openalex_id(i) for i in referenced_ids if i]
        ids = [i for i in ids if i][:limit]
        if not ids:
            return []

        out: List[Dict] = []
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            url = (
                f"{CitationTracker.OPENALEX_API}"
                f"?filter=openalex_id:{'|'.join(batch)}"
                f"&per_page=50&select=id,doi,title,publication_year"
            )
            data = CitationTracker._get(url)
            if not data:
                # Keep the ids even when the lookup fails - a bare OpenAlex id
                # is still a usable edge endpoint, just an unlabelled one.
                out.extend(
                    {"openalex_id": i, "doi": "", "title": "", "year": None}
                    for i in batch
                )
                continue
            found = {
                short_openalex_id(w.get("id")): CitationTracker._work_summary(w)
                for w in data.get("results", [])
            }
            for i in batch:
                out.append(
                    found.get(
                        i, {"openalex_id": i, "doi": "", "title": "", "year": None}
                    )
                )
        return out

    @staticmethod
    def _local_ids_by_doi(session, dois: Iterable[str]) -> Dict[str, int]:
        """Map bare DOIs to local Item ids, for the edges whose other end we
        do happen to hold."""
        wanted = {d for d in (normalise_doi(x) for x in dois) if d}
        if not wanted:
            return {}
        found: Dict[str, int] = {}
        wanted_list = sorted(wanted)
        for start in range(0, len(wanted_list), 500):
            batch = wanted_list[start : start + 500]
            rows = (
                session.query(Item.id, Item.doi)
                .filter(func.lower(Item.doi).in_(batch))
                .all()
            )
            for item_id, doi in rows:
                found[normalise_doi(doi)] = item_id
        return found

    @staticmethod
    def sync_citation_graph(
        item_id: int,
        max_citing: Optional[int] = None,
        max_references: Optional[int] = None,
    ) -> Dict:
        """Store both directions of one record's citation graph.

        Returns a summary rather than a bool: callers want to know how much
        of the graph was actually captured, and "0 edges" is a legitimate
        result for an uncited record, not a failure.
        """
        max_citing = (
            CitationTracker.MAX_CITING_EDGES if max_citing is None else max_citing
        )
        max_references = (
            CitationTracker.MAX_REFERENCE_EDGES
            if max_references is None
            else max_references
        )

        summary = {
            "item_id": item_id,
            "citing_edges": 0,
            "reference_edges": 0,
            "new_edges": 0,
            "cited_by_count": 0,
            "status": "ok",
        }

        session = SessionLocal()
        try:
            item = session.query(Item).filter_by(id=item_id).first()
            if not item:
                summary["status"] = "not_found"
                return summary
            if not (item.doi or item.openalex_id):
                summary["status"] = "no_identifier"
                return summary

            work = CitationTracker.fetch_work(
                doi=item.doi or "", openalex_id=item.openalex_id or ""
            )
            if not work:
                summary["status"] = "not_in_openalex"
                return summary

            self_ident = {
                "item_id": item.id,
                "doi": item.doi,
                "openalex_id": short_openalex_id(work.get("id")),
                "title": item.title,
            }
            summary["cited_by_count"] = work.get("cited_by_count", 0) or 0

            # Record the OpenAlex id we just resolved, so the next sync (and
            # the African-share lookup) skips the DOI round trip.
            if not item.openalex_id and self_ident["openalex_id"]:
                item.openalex_id = self_ident["openalex_id"]
            if summary["cited_by_count"] > (item.cited_by_count or 0):
                item.cited_by_count = summary["cited_by_count"]

            citing = (
                CitationTracker.fetch_citing_works(
                    self_ident["openalex_id"], limit=max_citing
                )
                if summary["cited_by_count"]
                else []
            )
            references = CitationTracker.fetch_referenced_works(
                work.get("referenced_works") or [], limit=max_references
            )
            summary["citing_edges"] = len(citing)
            summary["reference_edges"] = len(references)

            local = CitationTracker._local_ids_by_doi(
                session,
                [c.get("doi") for c in citing] + [r.get("doi") for r in references],
            )

            pending: Dict[str, Citation] = {}
            for other in citing:
                # other cites this item
                key = edge_key(other, self_ident)
                pending[key] = Citation(
                    citing_item_id=local.get(normalise_doi(other.get("doi"))),
                    cited_item_id=item.id,
                    citing_doi=other.get("doi") or None,
                    citing_openalex_id=other.get("openalex_id") or None,
                    citing_title=other.get("title") or None,
                    citing_year=other.get("year"),
                    cited_doi=normalise_doi(item.doi) or None,
                    cited_openalex_id=self_ident["openalex_id"] or None,
                    cited_title=item.title,
                    cited_year=(
                        item.publication_date.year if item.publication_date else None
                    ),
                    citation_date=(
                        datetime(other["year"], 1, 1) if other.get("year") else None
                    ),
                    source="openalex",
                    edge_key=key,
                )

            for other in references:
                # this item cites other
                key = edge_key(self_ident, other)
                pending[key] = Citation(
                    citing_item_id=item.id,
                    cited_item_id=local.get(normalise_doi(other.get("doi"))),
                    citing_doi=normalise_doi(item.doi) or None,
                    citing_openalex_id=self_ident["openalex_id"] or None,
                    citing_title=item.title,
                    citing_year=(
                        item.publication_date.year if item.publication_date else None
                    ),
                    cited_doi=other.get("doi") or None,
                    cited_openalex_id=other.get("openalex_id") or None,
                    cited_title=other.get("title") or None,
                    cited_year=other.get("year"),
                    citation_date=(
                        item.publication_date if item.publication_date else None
                    ),
                    source="openalex",
                    edge_key=key,
                )

            if pending:
                keys = list(pending)
                seen: set = set()
                for start in range(0, len(keys), 500):
                    batch = keys[start : start + 500]
                    seen.update(
                        k
                        for (k,) in session.query(Citation.edge_key)
                        .filter(Citation.edge_key.in_(batch))
                        .all()
                    )
                for key, row in pending.items():
                    if key not in seen:
                        session.add(row)
                        summary["new_edges"] += 1

            metrics = session.query(CitationMetrics).filter_by(item_id=item_id).first()
            if not metrics:
                metrics = CitationMetrics(item_id=item_id)
                session.add(metrics)
            metrics.citation_count = max(
                metrics.citation_count or 0, summary["cited_by_count"]
            )
            metrics.last_updated = datetime.utcnow()

            session.commit()
            logger.info("citation graph synced: %s", summary)
            return summary

        except Exception as e:
            session.rollback()
            logger.error(f"sync_citation_graph failed for item {item_id}: {e}")
            summary["status"] = "error"
            summary["error"] = str(e)
            return summary
        finally:
            session.close()

    @staticmethod
    def sync_citation_graph_bulk(
        limit: int = 50, sc_only: bool = True, force: bool = False
    ) -> Dict:
        """Sync the graph for records that have an identifier but no edges yet.

        Defaults to Special Collections only: those are the records the
        partner integration and the analytics actually surface, and a full
        corpus sync is a few thousand OpenAlex round trips.
        """
        session = SessionLocal()
        stats = {"attempted": 0, "synced": 0, "skipped": 0, "new_edges": 0}
        try:
            q = session.query(Item.id).filter(
                (Item.doi.isnot(None)) | (Item.openalex_id.isnot(None))
            )
            if sc_only:
                q = q.filter(SC_FILTER)
            if not force:
                cutoff = datetime.utcnow() - timedelta(days=30)
                q = q.outerjoin(
                    CitationMetrics, CitationMetrics.item_id == Item.id
                ).filter(
                    (CitationMetrics.last_updated.is_(None))
                    | (CitationMetrics.last_updated < cutoff)
                )
            ids = [row[0] for row in q.limit(limit).all()]
        finally:
            session.close()

        for item_id in ids:
            stats["attempted"] += 1
            result = CitationTracker.sync_citation_graph(item_id)
            if result.get("status") == "ok":
                stats["synced"] += 1
                stats["new_edges"] += result.get("new_edges", 0)
            else:
                stats["skipped"] += 1
        logger.info("bulk citation graph sync: %s", stats)
        return stats

    @staticmethod
    def update_paper_citations(item_id: int) -> bool:
        """Update citation metrics for a single paper."""
        session = SessionLocal()
        try:
            item = session.query(Item).filter_by(id=item_id).first()
            if not item or not item.doi:
                return False

            # Try OpenAlex first (more detailed)
            oa_data = CitationTracker.fetch_citations_openalex(item.doi)

            if oa_data:
                citation_count = oa_data["citation_count"]

                # Update or create metrics
                metrics = (
                    session.query(CitationMetrics).filter_by(item_id=item_id).first()
                )
                if not metrics:
                    metrics = CitationMetrics(item_id=item_id)
                    session.add(metrics)

                metrics.citation_count = citation_count
                metrics.last_updated = datetime.utcnow()

                # Store citation relationships
                for cite in oa_data["citations"]:
                    if cite["doi"]:
                        # Check if citing paper exists in our DB
                        citing_item = (
                            session.query(Item).filter_by(doi=cite["doi"]).first()
                        )
                        if citing_item:
                            # Create citation link
                            existing = (
                                session.query(Citation)
                                .filter_by(
                                    citing_item_id=citing_item.id, cited_item_id=item_id
                                )
                                .first()
                            )

                            if not existing:
                                citation = Citation(
                                    citing_item_id=citing_item.id,
                                    cited_item_id=item_id,
                                    citation_date=(
                                        datetime(cite["year"], 1, 1)
                                        if cite["year"]
                                        else None
                                    ),
                                    source="openalex",
                                )
                                session.add(citation)

                session.commit()
                logger.info(
                    f"Updated citations for item {item_id}: {citation_count} citations"
                )
                return True

            # Fallback to Crossref
            cr_count = CitationTracker.fetch_citations_crossref(item.doi)
            if cr_count is not None:
                metrics = (
                    session.query(CitationMetrics).filter_by(item_id=item_id).first()
                )
                if not metrics:
                    metrics = CitationMetrics(item_id=item_id)
                    session.add(metrics)

                metrics.citation_count = cr_count
                metrics.last_updated = datetime.utcnow()
                session.commit()
                return True

            return False

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update citations for item {item_id}: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def calculate_h_index(citation_counts: List[int]) -> int:
        """
        Calculate h-index from list of citation counts.
        h-index = largest number h such that h papers have at least h citations each.

        Example: [100, 50, 30, 20, 15, 10, 8, 5, 3, 2, 1, 1, 0, 0]
        - Paper 1: 100 citations >= 1, counts
        - Paper 2: 50 citations >= 2, counts
        - ...
        - Paper 10: 2 citations >= 10, does not count
        Result: h-index = 9
        """
        if not citation_counts:
            return 0

        sorted_counts = sorted(citation_counts, reverse=True)
        h = 0
        for i, count in enumerate(sorted_counts, start=1):
            if count >= i:
                h = i
            else:
                break
        return h

    @staticmethod
    def update_author_metrics(author_id: int) -> bool:
        """Calculate and update bibliometric indicators for an author."""
        session = SessionLocal()
        try:
            author = session.query(Author).filter_by(id=author_id).first()
            if not author:
                return False

            # Get all papers by this author with citation metrics
            papers = (
                session.query(Item, CitationMetrics)
                .join(Item.authors)
                .outerjoin(CitationMetrics, CitationMetrics.item_id == Item.id)
                .filter(Author.id == author_id)
                .all()
            )

            if not papers:
                return False

            citation_counts = [m.citation_count if m else 0 for _, m in papers]
            total_citations = sum(citation_counts)
            h_index = CitationTracker.calculate_h_index(citation_counts)
            i10_index = sum(1 for c in citation_counts if c >= 10)

            # Update or create author metrics
            metrics = (
                session.query(AuthorMetrics).filter_by(author_id=author_id).first()
            )
            if not metrics:
                metrics = AuthorMetrics(author_id=author_id)
                session.add(metrics)

            metrics.total_citations = total_citations
            metrics.h_index = h_index
            metrics.i10_index = i10_index
            metrics.total_papers = len(papers)
            metrics.last_updated = datetime.utcnow()

            session.commit()
            logger.info(
                f"Updated metrics for author {author.name}: h-index={h_index}, citations={total_citations}"
            )
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update author metrics for {author_id}: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def bulk_update_citations(limit: int = 100, force: bool = False) -> Dict:
        """
        Update citations for papers that haven't been updated recently.

        Args:
            limit: Maximum number of papers to update
            force: Update all papers regardless of last update time

        Returns:
            {'updated': int, 'failed': int, 'skipped': int}
        """
        session = SessionLocal()
        stats = {"updated": 0, "failed": 0, "skipped": 0}

        try:
            # Find papers with DOIs that need updating
            cutoff_date = datetime.utcnow() - timedelta(days=7)  # Update weekly

            query = session.query(Item).filter(Item.doi.isnot(None))

            if not force:
                # Only update papers not updated in last 7 days
                query = query.outerjoin(CitationMetrics).filter(
                    (CitationMetrics.last_updated.is_(None))
                    | (CitationMetrics.last_updated < cutoff_date)
                )

            papers = query.limit(limit).all()

            for paper in papers:
                success = CitationTracker.update_paper_citations(paper.id)
                if success:
                    stats["updated"] += 1
                else:
                    stats["failed"] += 1

            logger.info(f"Bulk citation update: {stats}")
            return stats

        finally:
            session.close()

    @staticmethod
    def fetch_work_velocity(openalex_id: str) -> Optional[Dict]:
        """Fetch counts_by_year + cited_by_count for one work from OpenAlex.

        Used by backfill_citation_velocity.py to fill gaps where the spider
        did not capture this data at crawl time.
        """
        try:
            url = f"https://api.openalex.org/works/{openalex_id}"
            headers = {"User-Agent": "URAAS/1.0 (mailto:library@unilag.edu.ng)"}
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                return None
            data = r.json()
            return {
                "counts_by_year": data.get("counts_by_year", []),
                "cited_by_count": data.get("cited_by_count", 0),
            }
        except Exception as e:
            logger.error(f"fetch_work_velocity failed for {openalex_id}: {e}")
            return None

    @staticmethod
    def fetch_african_citation_share(openalex_id: str) -> Optional[float]:
        """Return the % of citations coming from African institutions (0-100).

        Calls OpenAlex with group_by=authorships.institutions.country_code on
        the set of works that cite the given work, then sums the African
        country buckets.  Returns None if the work has no citations or the API
        call fails.
        """
        try:
            url = (
                f"https://api.openalex.org/works"
                f"?filter=cites:{openalex_id}"
                f"&group_by=authorships.institutions.country_code"
                f"&per_page=200"
            )
            headers = {"User-Agent": "URAAS/1.0 (mailto:library@unilag.edu.ng)"}
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                return None
            groups = r.json().get("group_by", [])
            if not groups:
                return None
            total = sum(g.get("count", 0) for g in groups)
            if not total:
                return None
            african = sum(
                g.get("count", 0)
                for g in groups
                if g.get("key", "").upper() in AFRICAN_ISO2
            )
            return round(african / total * 100, 1)
        except Exception as e:
            logger.error(f"fetch_african_citation_share failed for {openalex_id}: {e}")
            return None


# -- API Helper Functions ------------------------------------------------------


def get_paper_citations(item_id: int, limit: int = 200) -> Dict:
    """Citation data for a paper, including both directions of its edge list.

    `citing_papers` are works that cite this record; `references` are works
    it cites. Most of both sets are external to the corpus, so each entry
    carries its own DOI/OpenAlex id and an `internal_id` that is null unless
    URAAS also holds that work as a record of its own.
    """
    session = SessionLocal()
    try:
        metrics = session.query(CitationMetrics).filter_by(item_id=item_id).first()
        # Item.cited_by_count is captured at crawl time from OpenAlex and is
        # authoritative; CitationMetrics only exists once a sync has run. Take
        # the higher of the two, so this agrees with /api/citations/<id>
        # instead of reporting 0 for a cited record whose graph is unsynced.
        crawled_count = (
            session.query(Item.cited_by_count).filter(Item.id == item_id).scalar() or 0
        )

        inbound = (
            session.query(Citation)
            .filter(Citation.cited_item_id == item_id)
            .order_by(Citation.citing_year.desc().nullslast())
            .limit(limit)
            .all()
        )
        outbound = (
            session.query(Citation)
            .filter(Citation.citing_item_id == item_id)
            .order_by(Citation.cited_year.desc().nullslast())
            .limit(limit)
            .all()
        )

        def inbound_row(edge: Citation) -> Dict:
            return {
                "internal_id": edge.citing_item_id,
                "title": edge.citing_title or "",
                "doi": edge.citing_doi or "",
                "openalex_id": edge.citing_openalex_id or "",
                "year": edge.citing_year,
                "source": edge.source,
            }

        def outbound_row(edge: Citation) -> Dict:
            return {
                "internal_id": edge.cited_item_id,
                "title": edge.cited_title or "",
                "doi": edge.cited_doi or "",
                "openalex_id": edge.cited_openalex_id or "",
                "year": edge.cited_year,
                "source": edge.source,
            }

        return {
            "citation_count": max(
                crawled_count, (metrics.citation_count or 0) if metrics else 0
            ),
            "last_updated": metrics.last_updated.isoformat() if metrics else None,
            "citing_papers": [inbound_row(e) for e in inbound],
            "references": [outbound_row(e) for e in outbound],
            "edges_stored": {"citing": len(inbound), "references": len(outbound)},
        }
    finally:
        session.close()


def get_citation_graph_coverage() -> Dict:
    """How much of the corpus has a stored citation graph.

    The honest answer to "can I build a related-works view on this yet?" -
    edge counts alone hide that they may all belong to a handful of records.
    """
    session = SessionLocal()
    try:
        total_edges = session.query(func.count(Citation.id)).scalar() or 0
        internal_edges = (
            session.query(func.count(Citation.id))
            .filter(Citation.citing_item_id.isnot(None))
            .filter(Citation.cited_item_id.isnot(None))
            .scalar()
            or 0
        )
        cited_covered = (
            session.query(func.count(func.distinct(Citation.cited_item_id)))
            .filter(Citation.cited_item_id.isnot(None))
            .scalar()
            or 0
        )
        citing_covered = (
            session.query(func.count(func.distinct(Citation.citing_item_id)))
            .filter(Citation.citing_item_id.isnot(None))
            .scalar()
            or 0
        )
        eligible = (
            session.query(func.count(Item.id))
            .filter((Item.doi.isnot(None)) | (Item.openalex_id.isnot(None)))
            .scalar()
            or 0
        )
        sc_eligible = (
            session.query(func.count(Item.id))
            .filter(SC_FILTER)
            .filter((Item.doi.isnot(None)) | (Item.openalex_id.isnot(None)))
            .scalar()
            or 0
        )
        return {
            "total_edges": total_edges,
            "edges_between_two_local_records": internal_edges,
            "records_with_inbound_edges": cited_covered,
            "records_with_outbound_edges": citing_covered,
            "records_eligible_for_sync": eligible,
            "special_collections_eligible_for_sync": sc_eligible,
        }
    finally:
        session.close()


def get_author_bibliometrics(author_id: int) -> Dict:
    """Get bibliometric indicators for an author."""
    session = SessionLocal()
    try:
        metrics = session.query(AuthorMetrics).filter_by(author_id=author_id).first()
        author = session.query(Author).filter_by(id=author_id).first()

        if not metrics or not author:
            return {}

        return {
            "author_name": author.name,
            "total_papers": metrics.total_papers,
            "total_citations": metrics.total_citations,
            "h_index": metrics.h_index,
            "i10_index": metrics.i10_index,
            "last_updated": metrics.last_updated.isoformat(),
            "citations_per_paper": (
                round(metrics.total_citations / metrics.total_papers, 1)
                if metrics.total_papers
                else 0
            ),
        }
    finally:
        session.close()
