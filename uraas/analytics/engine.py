"""
URAAS Analytics Engine
Implements all APA Intelligence & Analytics Platform metrics:
  - Standard repository analytics (papers, authors, faculties, OA)
  - TK Vitality Score  (indigenous knowledge health index)
  - Linguistic Diversity Index  (African vs colonial language output)
  - Patent-to-Paper Velocity  (innovation lifecycle timing)
  - Multi-institution Comparator  (ROR-based benchmarking)
  - SDG Alignment  (UN Sustainable Development Goals) — AI-powered via spaCy
  - Keyword Cloud  (AI-extracted terms)
  - Collaboration Network  (D3 force graph data)
  - Special Collections (African Literature, Indigenous Knowledge, etc.)
"""

import itertools
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import desc, extract, func, or_
from sqlalchemy.orm import joinedload

from uraas.config.institutions import get_registry
from uraas.database import (
    Author,
    Collection,
    Community,
    File,
    Item,
    SessionLocal,
    db_year,
    db_year_month,
)
from uraas.utils.ai_classifier import (
    SPECIAL_COLLECTIONS,
    classify_special_collections,
    extract_keywords,
    extract_trends_from_corpus,
)
from uraas.utils.analytics_cache import analytics_cache
from uraas.utils.unilag_classifier import classifier

logger = logging.getLogger(__name__)

# African language codes (kept here for Linguistic Diversity Index)
AFRICAN_LANG_CODES = {
    "yo": "Yoruba",
    "ig": "Igbo",
    "ha": "Hausa",
    "sw": "Swahili",
    "am": "Amharic",
    "so": "Somali",
    "rw": "Kinyarwanda",
    "sn": "Shona",
    "zu": "Zulu",
    "xh": "Xhosa",
    "af": "Afrikaans",
    "st": "Sesotho",
    "tn": "Setswana",
    "ts": "Tsonga",
    "ss": "Swati",
    "ve": "Venda",
    "nr": "Ndebele",
    "ff": "Fula",
    "wo": "Wolof",
    "bm": "Bambara",
    "ln": "Lingala",
    "kg": "Kongo",
    "lua": "Luba",
    "om": "Oromo",
}

# Content type weights for TK Vitality Score
TK_WEIGHTS = {
    "indigenous_knowledge": 3.0,
    "cultural_heritage": 2.5,
    "oral_tradition": 2.5,
    "grey_literature": 1.5,
    "thesis": 1.2,
    "dataset": 1.2,
    "patent": 1.0,
    "research_paper": 0.5,
}

# Common stop words for legacy keyword code
STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "have",
    "been",
    "were",
    "their",
    "which",
    "these",
    "about",
    "other",
    "into",
    "than",
    "more",
    "such",
    "some",
    "what",
    "when",
    "where",
    "there",
    "also",
    "using",
    "used",
    "study",
    "show",
    "paper",
    "research",
    "analysis",
    "findings",
    "results",
    "between",
    "effect",
    "impact",
    "based",
    "data",
    "method",
    "approach",
    "model",
    "system",
    "review",
    "case",
    "report",
    "among",
    "within",
    "across",
    "during",
    "after",
    "before",
    "through",
    "while",
    "both",
    "each",
    "only",
    "very",
    "well",
    "high",
    "low",
    "new",
    "large",
    "small",
    "significant",
    "different",
    "similar",
    "total",
    "however",
    "therefore",
    "thus",
    "hence",
    "although",
    "despite",
}


class URAASAnalyticsEngine:
    """
    Observer Engine for the APA Intelligence & Analytics Platform.
    All methods return plain dicts/lists  no ORM objects leak out.
    """

    #  Helpers

    def _resolve_institution_name(self, identifier: Optional[str]) -> Optional[str]:
        """Maps short name or ROR to full institution name from registry."""
        if not identifier:
            return None
        reg = get_registry()
        inst = reg.get(identifier)
        return inst.name if inst else identifier

    @staticmethod
    def _is_oa(item: Item) -> bool:
        return "openAccess" in (item.dc_rights or "")

    @staticmethod
    def _year(item: Item) -> Optional[int]:
        return item.publication_date.year if item.publication_date else None

    def _get_sc_item_ids(self, session, institution: Optional[str] = None) -> List[int]:
        """
        Returns a list of Item IDs that match the Special Collections criteria.
        This forms the core pivot of the dashboard, restricting all analytics
        exclusively to papers focused on Special Collections.
        """
        inst_name = self._resolve_institution_name(institution)
        cache_key = f"sc_item_ids_{inst_name or 'all'}"
        cached = analytics_cache.get(cache_key)
        if cached is not None:
            return cached

        q = session.query(Item.id, Item.title, Item.abstract, Item.dc_subject)
        if inst_name:
            q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
        items = q.all()

        valid_ids = []
        for item_id, title, abstract, dc_subject in items:
            cats = classify_special_collections(
                title or "", abstract or "", dc_subject or ""
            )
            if cats:  # if it matched at least one special collection category
                valid_ids.append(item_id)

        analytics_cache.set(cache_key, valid_ids, ttl=3600)  # cache for 1 hour
        return valid_ids

    #  Standard repository analytics

    def get_top_authors(
        self,
        limit: int = 15,
        community_id: Optional[int] = None,
        institution: Optional[str] = None,
    ) -> List[Dict]:
        session = SessionLocal()
        try:
            q = session.query(
                Author.name,
                Author.orcid,
                Author.ror,
                func.count(Item.id).label("count"),
            ).join(Author.items)
            if community_id:
                q = (
                    q.join(Item.collections)
                    .join(Collection.community)
                    .filter(Community.id == community_id)
                )
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            rows = (
                q.group_by(Author.name, Author.orcid, Author.ror)
                .order_by(desc("count"))
                .limit(limit)
                .all()
            )
            return [
                {"author": r[0], "orcid": r[1] or "", "ror": r[2] or "", "count": r[3]}
                for r in rows
            ]
        except Exception as e:
            logger.error("get_top_authors: %s", e)
            return []
        finally:
            session.close()

    def get_department_collaboration_network(
        self, institution: Optional[str] = None
    ) -> List[Dict]:
        session = SessionLocal()
        try:
            sc_ids = self._get_sc_item_ids(session, institution)
            if not sc_ids:
                return []
            docs = (
                session.query(Item)
                .filter(Item.id.in_(sc_ids))
                .options(joinedload(Item.collections))
                .all()
            )
            edges: Dict[Tuple, int] = {}
            for doc in docs:
                colls = sorted(c.name for c in doc.collections if c and c.name)
                for pair in itertools.combinations(colls, 2):
                    edges[pair] = edges.get(pair, 0) + 1
            return [
                {"source": k[0], "target": k[1], "weight": v} for k, v in edges.items()
            ]
        except Exception as e:
            logger.error("get_department_collaboration_network: %s", e)
            return []
        finally:
            session.close()

    def get_papers_by_faculty_and_department(
        self, institution: Optional[str] = None
    ) -> Dict:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            communities = (
                session.query(Community)
                .options(joinedload(Community.collections))
                .all()
            )
            tree: Dict = {}
            seen: set = set()

            for comm in communities:
                dept_map: Dict = {}
                for coll in comm.collections:
                    q = (
                        session.query(Item)
                        .join(Item.collections)
                        .filter(Collection.id == coll.id)
                    )
                    if inst_name:
                        q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
                    sc_ids = self._get_sc_item_ids(session, institution)
                    if sc_ids:
                        q = q.filter(Item.id.in_(sc_ids))
                    else:
                        continue

                    papers = q.all()
                    paper_list = []
                    for p in papers:
                        seen.add(p.id)
                        f = session.query(File).filter_by(item_id=p.id).first()
                        paper_list.append(
                            {
                                "id": p.id,
                                "title": p.title or "Untitled",
                                "doi": p.doi or "",
                                "url": p.url or "",
                                "docid": p.docid or "",
                                "has_local_pdf": f is not None,
                                "access_policy": f.access_policy if f else None,
                                "download_url": (
                                    f"/api/papers/{p.id}/download" if f else None
                                ),
                            }
                        )
                    if paper_list:
                        dept_map[coll.name] = paper_list
                if dept_map:
                    tree[comm.name] = dept_map

            # Unclassified bucket
            unclassified_q = (
                session.query(Item).filter(~Item.id.in_(seen))
                if seen
                else session.query(Item)
            )
            if inst_name:
                unclassified_q = unclassified_q.filter(
                    Item.institution.ilike(f"%{inst_name}%")
                )
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                unclassified_q = unclassified_q.filter(Item.id.in_(sc_ids))
            unclassified = unclassified_q.all()
            if unclassified:
                tree["Unclassified"] = {
                    "General": [
                        {
                            "id": p.id,
                            "title": p.title or "Untitled",
                            "doi": p.doi or "",
                            "url": p.url or "",
                            "docid": p.docid or "",
                            "has_local_pdf": False,
                        }
                        for p in unclassified
                    ]
                }
            return tree
        except Exception as e:
            logger.error("get_papers_by_faculty_and_department: %s", e)
            return {}
        finally:
            session.close()

    def get_publications_by_year(self, institution: Optional[str] = None) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = session.query(db_year(Item.publication_date), func.count(Item.id))
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            q = (
                q.filter(Item.publication_date.isnot(None))
                .group_by(db_year(Item.publication_date))
                .order_by(db_year(Item.publication_date))
            )
            return [{"year": int(r[0]) if r[0] else 0, "count": r[1]} for r in q.all()]
        finally:
            session.close()

    def get_papers_by_year_faculty(
        self, institution: Optional[str] = None
    ) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = (
                session.query(
                    db_year(Item.publication_date), Community.name, func.count(Item.id)
                )
                .join(Item.collections)
                .join(Collection.community)
            )
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            q = q.filter(Item.publication_date.isnot(None)).group_by(
                db_year(Item.publication_date), Community.name
            )
            return [
                {"year": int(r[0]) if r[0] else 0, "faculty": r[1], "count": r[2]}
                for r in q.all()
            ]
        finally:
            session.close()

    def get_papers_by_faculty(self, institution: Optional[str] = None) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = (
                session.query(Community.name, func.count(Item.id))
                .join(Item.collections)
                .join(Collection.community)
            )
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            q = q.group_by(Community.name).order_by(desc(func.count(Item.id)))
            return [{"faculty": r[0], "count": r[1]} for r in q.all()]
        finally:
            session.close()

    def get_open_access_breakdown(
        self, institution: Optional[str] = None
    ) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = session.query(Item.dc_rights)
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            items = q.all()
            counts = {"Open Access": 0, "Restricted": 0}
            for it in items:
                if "openAccess" in (it[0] or ""):
                    counts["Open Access"] += 1
                else:
                    counts["Restricted"] += 1
            return [{"label": k, "value": v} for k, v in counts.items()]
        finally:
            session.close()

    def get_authors_by_papers(
        self, limit: int = 10, institution: Optional[str] = None
    ) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = session.query(Author.name, func.count(Item.id)).join(Author.items)
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            q = q.group_by(Author.name).order_by(desc(func.count(Item.id))).limit(limit)
            return [{"author": r[0], "count": r[1]} for r in q.all()]
        finally:
            session.close()

    def get_faculty_oa_breakdown(self, institution: Optional[str] = None) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = (
                session.query(Community.name, Item.dc_rights)
                .join(Item.collections)
                .join(Collection.community)
            )
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            rows = q.all()
            facs = defaultdict(lambda: {"oa": 0, "restricted": 0})
            for fac, rights in rows:
                if "openAccess" in (rights or ""):
                    facs[fac]["oa"] += 1
                else:
                    facs[fac]["restricted"] += 1
            return [
                {"faculty": k, "oa": v["oa"], "restricted": v["restricted"]}
                for k, v in facs.items()
            ]
        finally:
            session.close()

    def get_institutional_growth(self, institution: Optional[str] = None) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = session.query(db_year_month(Item.created_at), func.count(Item.id))
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            q = q.group_by(db_year_month(Item.created_at)).order_by(
                db_year_month(Item.created_at)
            )
            return [{"month": r[0], "count": r[1]} for r in q.all()]
        finally:
            session.close()

    def get_timeline_data(self, institution: Optional[str] = None) -> List[Dict]:
        inst_name = self._resolve_institution_name(institution)
        session = SessionLocal()
        try:
            q = session.query(func.date(Item.created_at), func.count(Item.id))
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            q = q.group_by(func.date(Item.created_at)).order_by(
                func.date(Item.created_at)
            )
            res = []
            total = 0
            for r in q.all():
                total += r[1]
                res.append({"date": r[0], "count": r[1], "total": total})
            return res
        finally:
            session.close()

    #  SDG Alignment (AI-powered, cached)

    def get_sdg_alignment(self, institution: Optional[str] = None) -> List[Dict]:
        """
        Score every paper against all 17 SDGs using AI.
        Results are cached for 30 minutes per institution.
        """
        inst_name = self._resolve_institution_name(institution)
        cache_key = f"sdg_alignment:{inst_name or 'all'}"
        cached = analytics_cache.get(cache_key)
        if cached is not None:
            return cached

        session = SessionLocal()
        try:
            q = session.query(Item.id, Item.title, Item.abstract)
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            items = q.all()

            # Pre-populate buckets for SDG 1 to 17
            sdg_buckets = {n: [] for n in range(1, 18)}
            sdg_names_full = {}
            for item_id, title, abstract in items:
                text_corpus = f"{title or ''} {abstract or ''}"
                hits = classifier.detect_sdg_alignment(text_corpus)
                for hit in hits:
                    sdg_str = hit["sdg"]  # e.g. "SDG 1 — No Poverty"
                    try:
                        num = int(re.search(r"SDG (\d+)", sdg_str).group(1))
                        sdg_names_full[num] = sdg_str
                        sdg_buckets[num].append(
                            {
                                "id": item_id,
                                "title": title,
                                "score": hit["score"],
                                "keywords": hit["matched_keywords"],
                            }
                        )
                    except (AttributeError, ValueError):
                        continue

            result = []
            for sdg_num, papers in sdg_buckets.items():
                if papers:
                    papers.sort(key=lambda x: -x["score"])
                    result.append(
                        {
                            "sdg": sdg_names_full.get(sdg_num, f"SDG {sdg_num}"),
                            "sdg_number": sdg_num,
                            "count": len(papers),
                            "papers": papers[:10],
                        }
                    )
            result.sort(key=lambda x: -x["count"])
            analytics_cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.error("get_sdg_alignment: %s", e)
            return []
        finally:
            session.close()

    def get_sdg_csv_data(self) -> List[List]:
        """
        Returns SDG alignment data as rows for CSV export.
        Header: [SDG Number, SDG Name, Paper Count, Paper Title, Score, Matched Keywords]
        """
        rows = [
            [
                "SDG Number",
                "SDG Name",
                "Paper Count",
                "Paper Title",
                "Score",
                "Matched Keywords",
            ]
        ]
        try:
            alignment = self.get_sdg_alignment()
            for entry in alignment:
                sdg_num = entry.get("sdg_number", "")
                sdg_name_full = entry.get("sdg", "")
                count = entry.get("count", 0)
                for paper in entry.get("papers", []):
                    rows.append(
                        [
                            sdg_num,
                            sdg_name_full,
                            count,
                            paper.get("title", ""),
                            paper.get("score", 0),
                            "; ".join(paper.get("keywords", [])),
                        ]
                    )
        except Exception as e:
            logger.error("get_sdg_csv_data: %s", e)
        return rows

    #  Keyword Cloud (corpus-level TF-IDF, cached)

    def get_keyword_cloud(
        self, top_n: int = 60, institution: Optional[str] = None
    ) -> List[Dict]:
        """Extract top keywords using corpus-level TF-IDF + spaCy NER. Cached 30 min."""
        inst_name = self._resolve_institution_name(institution)
        cache_key = f"keyword_cloud:{inst_name or 'all'}:{top_n}"
        cached = analytics_cache.get(cache_key)
        if cached is not None:
            return cached

        session = SessionLocal()
        try:
            q = session.query(Item.title, Item.abstract)
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            items = q.all()

            # Build corpus for IDF calculation
            all_texts = [f"{t or ''} {a or ''}" for t, a in items]
            combined_title = " ".join(t or "" for t, _ in items)
            combined_abstract = " ".join(a or "" for _, a in items)

            keywords = extract_keywords(
                combined_title, combined_abstract, top_n=top_n, all_texts=all_texts
            )
            result = [
                {"word": k["word"], "count": k["count"], "score": k["score"]}
                for k in keywords
            ]
            analytics_cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.error("get_keyword_cloud: %s", e)
            return []
        finally:
            session.close()

    #  APA Novel Metrics

    def get_institution_leaderboard(self) -> List[Dict]:
        """Cross-institution leaderboard ranked across key metrics."""
        cache_key = "institution_leaderboard"
        cached = analytics_cache.get(cache_key)
        if cached is not None:
            return cached

        session = SessionLocal()
        try:
            # Get distinct institutions in the DB
            inst_rows = (
                session.query(Item.institution, func.count(Item.id).label("total"))
                .filter(Item.institution.isnot(None))
                .group_by(Item.institution)
                .all()
            )

            leaderboard = []
            for inst_name, total in inst_rows:
                oa = (
                    session.query(Item)
                    .filter(
                        Item.institution == inst_name,
                        Item.dc_rights.like("%openAccess%"),
                    )
                    .count()
                )
                authors = (
                    session.query(func.count(func.distinct(Author.id)))
                    .join(Author.items)
                    .filter(Item.institution == inst_name)
                    .scalar()
                    or 0
                )

                oa_rate = round(oa / total * 100, 1) if total else 0
                leaderboard.append(
                    {
                        "institution": inst_name,
                        "total_papers": total,
                        "open_access": oa,
                        "oa_rate": oa_rate,
                        "unique_authors": authors,
                        "score": round(total * 0.4 + oa_rate * 0.4 + authors * 0.2, 1),
                    }
                )

            leaderboard.sort(key=lambda x: -x["score"])
            for i, inst in enumerate(leaderboard):
                inst["rank"] = i + 1

            analytics_cache.set(cache_key, leaderboard)
            return leaderboard
        except Exception as e:
            logger.error("get_institution_leaderboard: %s", e)
            return []
        finally:
            session.close()

    def get_tk_vitality_score(self, institution: Optional[str] = None) -> Dict:
        """
        TK Vitality Score  measures how well the institution is digitising
        indigenous knowledge and cultural heritage.

        Score = weighted sum of content types / total items * 100
        Max theoretical score = 100 (all items are indigenous knowledge)
        """
        inst_name = self._resolve_institution_name(institution)
        cache_key = f"tk_vitality:{inst_name or 'all'}"
        cached = analytics_cache.get(cache_key)
        if cached is not None:
            return cached

        session = SessionLocal()
        try:
            q = session.query(Item.content_type, Item.tk_label, Item.dc_type)
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []
            items = q.all()
            total = len(items)
            if total == 0:
                return {"score": 0, "breakdown": {}, "total_items": 0, "tk_items": 0}

            type_counts: Dict[str, int] = defaultdict(int)
            weighted_sum = 0.0
            tk_items = 0

            for content_type, tk_label, dc_type in items:
                ct = content_type or "research_paper"
                # Upgrade type if TK label is present
                if tk_label:
                    ct = "indigenous_knowledge"
                    tk_items += 1
                elif dc_type and "cultural" in (dc_type or "").lower():
                    ct = "cultural_heritage"
                    tk_items += 1

                type_counts[ct] += 1
                weighted_sum += TK_WEIGHTS.get(ct, 0.5)

            max_possible = total * TK_WEIGHTS["indigenous_knowledge"]
            score = round((weighted_sum / max_possible) * 100, 1) if max_possible else 0

            result = {
                "score": score,
                "breakdown": dict(type_counts),
                "total_items": total,
                "tk_items": tk_items,
                "tk_percentage": round(tk_items / total * 100, 1) if total else 0,
                "interpretation": (
                    "Excellent"
                    if score >= 60
                    else "Good" if score >= 30 else "Developing"
                ),
            }
            analytics_cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.error("get_tk_vitality_score: %s", e)
            return {"score": 0, "breakdown": {}, "total_items": 0, "tk_items": 0}
        finally:
            session.close()

    def get_linguistic_diversity_index(self) -> Dict:
        """
        Linguistic Diversity Index  % of outputs in African languages vs English/French.
        Supports the decolonisation of knowledge mission.
        """
        session = SessionLocal()
        try:
            items = session.query(
                Item.language_code, Item.is_african_language, Item.dc_language
            ).all()
            total = len(items)
            if total == 0:
                return {"index": 0, "african_count": 0, "total": 0, "breakdown": {}}

            lang_counts: Dict[str, int] = defaultdict(int)
            african_count = 0

            for lang_code, is_african, dc_lang in items:
                code = lang_code or dc_lang or "en"
                lang_counts[code] += 1
                if is_african or code in AFRICAN_LANG_CODES:
                    african_count += 1

            index = round(african_count / total * 100, 1)

            # Build human-readable breakdown
            breakdown = {}
            for code, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
                label = AFRICAN_LANG_CODES.get(code, code.upper())
                breakdown[label] = count

            return {
                "index": index,
                "african_count": african_count,
                "colonial_count": total - african_count,
                "total": total,
                "breakdown": breakdown,
                "top_african_languages": [
                    {"language": AFRICAN_LANG_CODES.get(c, c), "code": c, "count": n}
                    for c, n in sorted(lang_counts.items(), key=lambda x: -x[1])
                    if c in AFRICAN_LANG_CODES
                ][:10],
            }
        except Exception as e:
            logger.error("get_linguistic_diversity_index: %s", e)
            return {"index": 0, "african_count": 0, "total": 0, "breakdown": {}}
        finally:
            session.close()

    def get_patent_velocity(self) -> Dict:
        """
        Patent-to-Paper Velocity  measures the innovation lifecycle.
        Calculates average days from paper publication to patent filing.
        """
        session = SessionLocal()
        try:
            items = (
                session.query(
                    Item.title, Item.publication_date, Item.patent_id, Item.patent_date
                )
                .filter(
                    Item.patent_id.isnot(None),
                    Item.publication_date.isnot(None),
                    Item.patent_date.isnot(None),
                )
                .all()
            )

            if not items:
                return {
                    "total_patents": 0,
                    "avg_days_to_patent": None,
                    "fast_movers": [],
                    "velocity_distribution": [],
                }

            velocities = []
            for title, pub_date, patent_id, patent_date in items:
                delta = (patent_date - pub_date).days
                if delta >= 0:
                    velocities.append(
                        {
                            "title": title,
                            "patent_id": patent_id,
                            "publication_date": pub_date.isoformat(),
                            "patent_date": patent_date.isoformat(),
                            "days_to_patent": delta,
                        }
                    )

            velocities.sort(key=lambda x: x["days_to_patent"])
            avg = (
                round(sum(v["days_to_patent"] for v in velocities) / len(velocities))
                if velocities
                else None
            )

            # Distribution buckets
            buckets = {"< 1 year": 0, "1-2 years": 0, "2-5 years": 0, "> 5 years": 0}
            for v in velocities:
                d = v["days_to_patent"]
                if d < 365:
                    buckets["< 1 year"] += 1
                elif d < 730:
                    buckets["1-2 years"] += 1
                elif d < 1825:
                    buckets["2-5 years"] += 1
                else:
                    buckets["> 5 years"] += 1

            return {
                "total_patents": len(velocities),
                "avg_days_to_patent": avg,
                "fast_movers": velocities[:10],
                "velocity_distribution": [
                    {"range": k, "count": v} for k, v in buckets.items()
                ],
            }
        except Exception as e:
            logger.error("get_patent_velocity: %s", e)
            return {
                "total_patents": 0,
                "avg_days_to_patent": None,
                "fast_movers": [],
                "velocity_distribution": [],
            }
        finally:
            session.close()

    def get_docid_coverage(self) -> Dict:
        """DocID assignment coverage across the repository."""
        session = SessionLocal()
        try:
            total = session.query(Item).count()
            with_docid = session.query(Item).filter(Item.docid.isnot(None)).count()
            coverage = round(with_docid / total * 100, 1) if total else 0

            # By content type
            by_type = (
                session.query(Item.content_type, func.count(Item.id))
                .filter(Item.docid.isnot(None))
                .group_by(Item.content_type)
                .all()
            )

            return {
                "total_papers": total,
                "docid_assigned": with_docid,
                "coverage_percent": coverage,
                "by_content_type": [
                    {"type": r[0] or "research_paper", "count": r[1]} for r in by_type
                ],
            }
        except Exception as e:
            logger.error("get_docid_coverage: %s", e)
            return {
                "total_papers": 0,
                "docid_assigned": 0,
                "coverage_percent": 0,
                "by_content_type": [],
            }
        finally:
            session.close()

    def get_special_collections_metrics(
        self, institution: Optional[str] = None
    ) -> Dict:
        """
        Special Collections Metrics using AI classifier. Cached 30 min.
        """
        inst_name = self._resolve_institution_name(institution)
        cache_key = f"special_collections:{inst_name or 'all'}"
        cached = analytics_cache.get(cache_key)
        if cached is not None:
            return cached

        session = SessionLocal()
        try:
            q = session.query(Item.id, Item.title, Item.abstract, Item.dc_subject)
            if inst_name:
                q = q.filter(Item.institution.ilike(f"%{inst_name}%"))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return {
                    "summary": [],
                    "total_special_items": 0,
                    "total_repository_items": q.count(),
                }
            items = q.all()
            results: Dict[str, List] = {cat: [] for cat in SPECIAL_COLLECTIONS}

            for item_id, title, abstract, dc_subject in items:
                cats = classify_special_collections(
                    title or "", abstract or "", dc_subject or ""
                )
                for cat_result in cats:
                    cat = cat_result["category"]
                    if cat in results:
                        results[cat].append(
                            {
                                "id": item_id,
                                "title": title,
                                "matches": cat_result["matched_keywords"],
                                "count": cat_result["score"],
                            }
                        )

            summary = []
            for category, papers in results.items():
                papers.sort(key=lambda x: -x["count"])
                summary.append(
                    {
                        "category": category,
                        "count": len(papers),
                        "top_papers": papers[:10],
                    }
                )

            summary.sort(key=lambda x: -x["count"])
            result = {
                "summary": summary,
                "total_special_items": sum(len(p) for p in results.values()),
                "total_repository_items": len(items),
            }
            analytics_cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.error("get_special_collections_metrics: %s", e)
            return {
                "summary": [],
                "total_special_items": 0,
                "total_repository_items": 0,
            }
        finally:
            session.close()

    def get_special_collections_csv_data(self) -> List[List]:
        """Returns special collections data as rows for CSV export."""
        rows = [["Category", "Paper Count", "Paper Title", "Score", "Matched Keywords"]]
        try:
            metrics = self.get_special_collections_metrics()
            for entry in metrics.get("summary", []):
                for paper in entry.get("top_papers", []):
                    rows.append(
                        [
                            entry.get("category", ""),
                            entry.get("count", 0),
                            paper.get("title", ""),
                            paper.get("count", 0),
                            "; ".join(paper.get("matches", [])),
                        ]
                    )
        except Exception as e:
            logger.error("get_special_collections_csv_data: %s", e)
        return rows

    def get_author_network(
        self, author_name: Optional[str] = None, limit: int = 30
    ) -> Dict:
        """
        Collaboration network for D3 force graph.
        If author_name given: ego-network for that researcher.
        Otherwise: top-N authors by paper count.
        """
        session = SessionLocal()
        try:
            if author_name:
                items = (
                    session.query(Item)
                    .join(Item.authors)
                    .filter(Author.name == author_name)
                    .options(joinedload(Item.authors))
                    .all()
                )
                edges: Dict[Tuple, int] = {}
                for item in items:
                    names = [a.name for a in item.authors]
                    if author_name not in names:
                        continue
                    for name in names:
                        if name != author_name:
                            key = tuple(sorted([author_name, name]))
                            edges[key] = edges.get(key, 0) + 1

                edge_list = sorted(
                    [
                        {"source": k[0], "target": k[1], "weight": v}
                        for k, v in edges.items()
                    ],
                    key=lambda x: -x["weight"],
                )[:15]

                collaborators = {e["source"] for e in edge_list} | {
                    e["target"] for e in edge_list
                }
                collaborators.discard(author_name)

                return {
                    "nodes": [{"id": author_name, "count": len(items)}]
                    + [{"id": c, "count": 0} for c in collaborators],
                    "edges": edge_list,
                }
            else:
                # Global top-N network
                top_rows = (
                    session.query(Author.name, func.count(Item.id).label("cnt"))
                    .join(Author.items)
                    .group_by(Author.name)
                    .order_by(desc("cnt"))
                    .limit(limit)
                    .all()
                )
                top_names = {r[0] for r in top_rows}
                node_counts = {r[0]: r[1] for r in top_rows}

                items = session.query(Item).options(joinedload(Item.authors)).all()
                edges: Dict[Tuple, int] = {}
                for item in items:
                    names = [a.name for a in item.authors if a.name in top_names]
                    for pair in itertools.combinations(sorted(names), 2):
                        edges[pair] = edges.get(pair, 0) + 1

                return {
                    "nodes": [{"id": n, "count": node_counts[n]} for n in top_names],
                    "edges": [
                        {"source": k[0], "target": k[1], "weight": v}
                        for k, v in edges.items()
                    ],
                }
        except Exception as e:
            logger.error("get_author_network: %s", e)
            return {"nodes": [], "edges": []}
        finally:
            session.close()


analytics = URAASAnalyticsEngine()
