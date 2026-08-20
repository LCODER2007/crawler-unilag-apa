"""
Semantic Scholar spider — queries the free S2 Graph API.

Semantic Scholar (semanticscholar.org) has broader humanities and social-science
coverage than arXiv, including African studies, philosophy, cultural heritage, and
postcolonial literature — exactly the SC categories URAAS cares about. The API is
free (no key required for basic use; 100 reqs/5 min per IP).

The spider runs two types of waves:
  • SC seed waves  — institution + each SC seed phrase (e.g. "indigenous knowledge")
  • General wave   — institution name alone (catches SC hits missed by seeds)

The SC classifier in the pipeline gates what actually gets saved.
"""

import os
import sys

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,authors,year,externalIds,openAccessPdf,fieldsOfStudy,venue"
_LIMIT = 100


class SemanticScholarSpider(DedupAwareSpiderMixin, scrapy.Spider):
    name = "semantic_scholar"
    custom_settings = {
        # S2 free tier: 100 req / 5 min per IP (~1 req/3 sec sustained).
        # When running alongside other spiders the shared IP exhausts the
        # budget quickly, so we use a conservative 3 s delay + autothrottle
        # with a generous max to absorb 429 bursts.
        "DOWNLOAD_DELAY": 6.0,
        "CONCURRENT_REQUESTS": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 6.0,
        "AUTOTHROTTLE_MAX_DELAY": 120.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
        "RETRY_BACKOFF_BASE": 6.0,
        "RETRY_BACKOFF_MAX": 120.0,
        "USER_AGENT": (
            f"URAAS/1.0 (+read-only SC discovery; mailto:{config.OPENALEX_MAILTO})"
        ),
        "HTTPERROR_ALLOWED_CODES": [429],
    }

    def __init__(
        self,
        institution="unilag",
        target=50,
        boost_special=True,
        sc_only=False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        _truthy = {"1", "true", "yes", "on"}
        self.boost_special = (
            boost_special.lower() in _truthy
            if isinstance(boost_special, str)
            else bool(boost_special)
        )
        self.sc_only = (
            sc_only.lower() in _truthy
            if isinstance(sc_only, str)
            else bool(sc_only)
        )
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0
        self.max_results_scanned = config.MAX_RESULTS_SCANNED

        self.logger.info(
            "S2 spider | %s | boost_special=%s | sc_only=%s | target=%d",
            self.institution_name,
            self.boost_special,
            self.sc_only,
            self.target_limit,
        )
        self._init_dedup_index()

    def _build_url(self, query: str, offset: int = 0) -> str:
        import urllib.parse
        q = urllib.parse.quote(query)
        return (
            f"{_S2_BASE}?query={q}"
            f"&fields={_FIELDS}"
            f"&limit={_LIMIT}"
            f"&offset={offset}"
        )

    def _institution_match(self, title: str, abstract: str, venue: str) -> bool:
        """
        S2 basic search doesn't return author affiliations, so we verify the
        institution appears anywhere in the available text fields.  This is
        intentionally lenient — a false negative (dropping a valid paper)
        is preferable to a false positive (storing a paper from the wrong
        university).
        """
        combined = f"{title} {abstract} {venue}".lower()
        return any(
            pat.lower() in combined
            for pat in self.institution_config.affiliation_patterns
        )

    def _headers(self) -> dict:
        # config.S2_API_KEY existed but was never actually sent — this spider
        # built requests with no headers at all. Live-tested 2026-07-18: a
        # burst at this spider's own configured 6s delay got HTTP 429 on 4/5
        # sequential requests, with the 429 body reading "apply for a key for
        # higher rate limits" — the one available lever that would help was
        # unused. S2's docs specify the `x-api-key` header for this.
        if config.S2_API_KEY:
            return {"x-api-key": config.S2_API_KEY}
        return {}

    async def start(self):
        if not self.sc_only:
            url = self._build_url(self.institution_name)
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                headers=self._headers(),
                meta={"wave": "general", "query": self.institution_name, "offset": 0},
            )

        if self.boost_special:
            # Cap at 8 highest-signal SC seeds to avoid exhausting the S2
            # 100 req/5 min budget before we get any results.
            _TOP_SEEDS = [
                "indigenous knowledge", "oral tradition", "african literature",
                "cultural heritage", "postcolonial", "ethnomusicology",
                "pan-african", "traditional medicine",
            ]
            for seed in _TOP_SEEDS:
                query = f"{self.institution_name} {seed}"
                url = self._build_url(query)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    headers=self._headers(),
                    meta={"wave": f"sc:{seed}", "query": query, "offset": 0},
                    priority=10,
                )

    def parse(self, response):
        if response.status == 429:
            self.logger.warning("S2 rate-limited (429) — request will be retried by Scrapy")
            return
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        data = response.json()
        papers = data.get("data", [])
        wave = response.meta.get("wave", "general")
        self.logger.info("[S2:%s] received %d papers", wave, len(papers))

        rejected_aff = 0
        for paper in papers:
            if self._accepted >= self.target_limit:
                return

            title = (paper.get("title") or "").strip()
            if not title:
                continue

            abstract = (paper.get("abstract") or "").strip()
            venue = (paper.get("venue") or "").strip()
            year = paper.get("year")
            pub_date = f"{year}-01-01" if year else ""

            ext_ids = paper.get("externalIds") or {}
            doi = ext_ids.get("DOI") or ext_ids.get("doi") or ""
            arxiv_id = ext_ids.get("ArXiv") or ""

            oa = paper.get("openAccessPdf") or {}
            pdf_url = oa.get("url") if oa else None

            url_val = (
                f"https://doi.org/{doi}" if doi
                else (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "")
            )

            authors = [
                a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")
            ]

            fields = []
            for f in (paper.get("fieldsOfStudy") or []):
                if isinstance(f, dict):
                    cat = f.get("category", "")
                    if cat:
                        fields.append(cat)
                elif isinstance(f, str) and f:
                    fields.append(f)
            dc_subject = ", ".join(fields[:6])

            # S2 doesn't return author affiliations in basic search at all.
            # A text mention of the institution can't distinguish a paper
            # genuinely authored there from one merely written about it —
            # cross-checking author names against the verified staff roster
            # is a materially stronger, independent signal; only fall back
            # to the weaker text match when no author matches the roster
            # (e.g. a genuine UNILAG researcher not yet in our harvested
            # roster), so recall isn't sacrificed outright for precision.
            roster_ok = self.institution_config.matches_staff_roster(authors)
            if not roster_ok and not self._institution_match(title, abstract, venue):
                rejected_aff += 1
                self.logger.debug(f"S2 aff FAIL: {title[:60]}")
                continue

            # SC gate — only count papers the storage pipeline will keep, so the
            # crawl keeps paginating until `target` real SC papers are found.
            if sc_score_of(title, abstract, dc_subject) <= 0.0:
                continue

            # Dedup gate — skip (don't count, but keep paginating past) papers
            # already in the DB.
            if self._is_known(doi=doi, url=url_val, title=title):
                continue

            self._accepted += 1
            item = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "doi": doi,
                "url": url_val,
                "pdf_url": pdf_url,
                "publication_date": pub_date,
                "source_repository": "Semantic Scholar",
                "is_unilag_author": True,
                "raw_affiliation": self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                "dc_subject": dc_subject,
                # "strong" only via the staff-roster cross-check — the
                # title/abstract/venue text fallback can't distinguish
                # authored-there from written-about.
                "affiliation_confidence": "strong" if roster_ok else "weak",
            }
            yield item
            self._mark_seen(doi=doi, url=url_val, title=title)

        # Offset-based pagination
        total = data.get("total", 0)
        offset = response.meta.get("offset", 0) + _LIMIT
        if offset < min(total, self.max_results_scanned) and self._accepted < self.target_limit:
            query = response.meta["query"]
            wave = response.meta["wave"]
            next_url = self._build_url(query, offset)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                headers=self._headers(),
                meta={"wave": wave, "query": query, "offset": offset},
            )

    def closed(self, reason):
        self.logger.info(
            "S2 spider closed | %s | accepted=%d | skipped_known=%d | reason=%s",
            self.institution_name,
            self._accepted,
            self._skipped_known,
            reason,
        )
        if self._accepted == 0:
            self.logger.warning(
                "S2: 0 papers accepted for %s — check institution affiliation_patterns",
                self.institution_name,
            )
