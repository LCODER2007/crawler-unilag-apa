"""
arXiv spider — uses the official Atom API (export.arxiv.org/api/query).

The HTML search page at arxiv.org/search was fragile and layout-dependent.
The Atom API is stable, rate-limit-friendly (1 req/3s recommended), and
returns clean structured XML metadata.

Docs: info.arxiv.org/help/api/basics.html
Rate limit: arXiv's own Terms of Use (info.arxiv.org/help/api/tou.html) say
"make no more than one request every three seconds" — i.e. DOWNLOAD_DELAY
must be >= 3.0s. This file's two rate-limit comments used to disagree with
each other (one said "1 req/3s", the other said "3 req/s" — a 10x gap) and
the configured delay (1.5s) matched neither, running at 2x the real allowed
rate.
"""

import os
import sys
from urllib.parse import urlencode
from xml.etree import ElementTree

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

_BASE = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
_BATCH = 50
# arXiv is primarily CS/STEM — only a few SC seed terms will yield results.
_SC_RELEVANT = {
    "indigenous", "cultural heritage", "traditional knowledge", "oral tradition",
    "ethnobotany", "decolonial", "african literature", "postcolonial",
}


class ArxivSpider(DedupAwareSpiderMixin, scrapy.Spider):
    name = "arxiv_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 3.0,
        "CONCURRENT_REQUESTS": 1,
        "USER_AGENT": f"URAAS/1.0 (+SC discovery; mailto:{config.OPENALEX_MAILTO})",
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
        self._seen_ids: set = set()
        self.max_results_scanned = config.MAX_RESULTS_SCANNED
        self._init_dedup_index()

    def _build_url(self, query: str, start: int = 0) -> str:
        params = {"search_query": query, "start": start, "max_results": _BATCH}
        return f"{_BASE}?{urlencode(params)}"

    async def start(self):
        seen_queries: set = set()

        if not self.sc_only:
            # Primary institution wave — exact phrase in all fields
            q = f'all:"{self.institution_name}"'
            seen_queries.add(q)
            yield scrapy.Request(
                self._build_url(q, 0),
                callback=self.parse,
                meta={"query": q, "start": 0},
            )

        if self.boost_special:
            # Combine institution with SC seeds that are relevant to arXiv
            inst_q = f'all:"{self.institution_name}"'
            priority_seeds = [
                s for s in SC_SEED_KEYWORDS
                if any(k in s.lower() for k in _SC_RELEVANT)
            ][:8]
            for seed in priority_seeds:
                q = f'{inst_q} AND all:"{seed}"'
                if q not in seen_queries:
                    seen_queries.add(q)
                    yield scrapy.Request(
                        self._build_url(q, 0),
                        callback=self.parse,
                        meta={"query": q, "start": 0},
                        priority=5,
                    )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError:
            self.logger.warning(f"arXiv XML parse error: {response.url[:120]}")
            return

        entries = root.findall("atom:entry", _NS)
        for entry in entries:
            if self._accepted >= self.target_limit:
                return

            arxiv_id = (entry.findtext("atom:id", "", _NS) or "").strip()
            if arxiv_id in self._seen_ids:
                continue
            self._seen_ids.add(arxiv_id)

            title = (
                (entry.findtext("atom:title", "", _NS) or "")
                .strip()
                .replace("\n", " ")
            )
            abstract = (
                (entry.findtext("atom:summary", "", _NS) or "")
                .strip()
                .replace("\n", " ")
            )
            if not title:
                continue

            authors = []
            for a in entry.findall("atom:author", _NS):
                name = (a.findtext("atom:name", "", _NS) or "").strip()
                if name:
                    authors.append(name)

            doi = (entry.findtext("arxiv:doi", "", _NS) or "").strip() or None
            pub_date = (entry.findtext("atom:published", "", _NS) or "")[:10]

            pdf_url = None
            for link in entry.findall("atom:link", _NS):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href")
                    break

            # Extract affiliations from arxiv:affiliation elements — populated
            # for only a minority of papers (live-verified: 0/3 on a sample
            # UNILAG query), but when present it's real per-author data, so
            # gate on it the same way openalex_spider.py's Gate 3 does: only
            # reject when structured data exists AND contradicts the query.
            affiliations = [
                aff.text.strip()
                for a in entry.findall("atom:author", _NS)
                for aff in a.findall("arxiv:affiliation", _NS)
                if aff.text
            ]
            raw_affiliation = "; ".join(affiliations) or self.institution_name
            if affiliations and not self.institution_config.matches_affiliation(
                raw_affiliation
            ):
                continue

            # When no structured affiliation data exists at all (the common
            # case), arXiv's `all:` query only guarantees the institution
            # name appears SOMEWHERE in title/abstract/authors/comments —
            # not that any author is actually affiliated there. That can't
            # distinguish a paper genuinely authored at the institution from
            # one merely written ABOUT it (confirmed live: a scientometric
            # study titled "Two Decades of Research at the University of
            # Lagos" passed this exact query with zero UNILAG authors).
            # Cross-checking author names against the verified staff roster
            # closes that gap — require a roster match when there's no
            # structured affiliation to fall back on.
            if not affiliations and not self.institution_config.matches_staff_roster(
                authors
            ):
                continue

            # SC gate — only count papers the storage pipeline will keep, so the
            # crawl keeps paginating until `target` real SC papers are found.
            if sc_score_of(title, abstract) <= 0.0:
                continue

            # Dedup gate — skip (don't count, but keep paginating past) papers
            # already in the DB.
            if self._is_known(doi=doi, url=arxiv_id, title=title):
                continue

            self._accepted += 1
            item = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "doi": doi,
                "url": arxiv_id,
                "pdf_url": pdf_url,
                "publication_date": pub_date,
                "source_repository": "arXiv",
                "is_unilag_author": True,
                "raw_affiliation": raw_affiliation,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
            }
            yield item
            self._mark_seen(doi=doi, url=arxiv_id, title=title)

        # Pagination
        total_text = root.findtext("opensearch:totalResults", "0", _NS) or "0"
        total = int(total_text) if total_text.isdigit() else 0
        query = response.meta.get("query", "")
        start = response.meta.get("start", 0)
        next_start = start + _BATCH
        if next_start < min(total, self.max_results_scanned) and self._accepted < self.target_limit:
            yield scrapy.Request(
                self._build_url(query, next_start),
                callback=self.parse,
                meta={"query": query, "start": next_start},
            )

    def closed(self, reason):
        self.logger.info(
            f"arXiv spider closed | {self.institution_name} | "
            f"accepted={self._accepted} | skipped_known={self._skipped_known} | reason={reason}"
        )
