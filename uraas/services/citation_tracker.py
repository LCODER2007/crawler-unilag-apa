"""
Citation Tracking Service
Fetches citation counts and citation graphs from OpenAlex and Crossref.
Calculates h-index and other bibliometric indicators.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from uraas.database import Author, Base, Item, SessionLocal

logger = logging.getLogger(__name__)


# ── New Database Models for Citations ────────────────────────────────────────


class Citation(Base):
    """Citation relationship between papers."""

    __tablename__ = "citations"

    id = Column(Integer, primary_key=True)
    citing_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"))
    cited_item_id = Column(Integer, ForeignKey("items.id", ondelete="CASCADE"))
    citation_date = Column(DateTime)
    source = Column(String(50))  # 'openalex', 'crossref', 'manual'

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


# ── Citation Fetching Service ─────────────────────────────────────────────────


class CitationTracker:
    """Fetches and tracks citations from external APIs."""

    OPENALEX_API = "https://api.openalex.org/works"
    CROSSREF_API = "https://api.crossref.org/works"

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
        - Paper 1: 100 citations ≥ 1 ✓
        - Paper 2: 50 citations ≥ 2 ✓
        - ...
        - Paper 10: 2 citations ≥ 10 ✗
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


# ── API Helper Functions ──────────────────────────────────────────────────────


def get_paper_citations(item_id: int) -> Dict:
    """Get citation data for a paper."""
    session = SessionLocal()
    try:
        metrics = session.query(CitationMetrics).filter_by(item_id=item_id).first()

        # Get citing papers
        citations = (
            session.query(Citation, Item)
            .join(Item, Citation.citing_item_id == Item.id)
            .filter(Citation.cited_item_id == item_id)
            .all()
        )

        return {
            "citation_count": metrics.citation_count if metrics else 0,
            "last_updated": metrics.last_updated.isoformat() if metrics else None,
            "citing_papers": [
                {
                    "id": item.id,
                    "title": item.title,
                    "doi": item.doi,
                    "year": (
                        item.publication_date.year if item.publication_date else None
                    ),
                    "authors": [a.name for a in item.authors[:3]],
                }
                for _, item in citations
            ],
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
