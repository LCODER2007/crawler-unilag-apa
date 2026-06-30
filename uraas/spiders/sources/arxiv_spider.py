"""
arXiv spider — uses the official Atom API (export.arxiv.org/api/query).

The HTML search page at arxiv.org/search was fragile and layout-dependent.
The Atom API is stable, rate-limit-friendly (1 req/3s recommended), and
returns clean structured XML metadata.

Docs: info.arxiv.org/help/api/basics.html
Rate limit: 3 req/s; we use 1.5s download delay to stay polite.
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
from uraas.utils.ai_classifier import sc_score_of

_BASE = "http://export.arxiv.org/api/query"
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


class ArxivSpider(scrapy.Spider):
    name = "arxiv_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
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
            return

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

            # Extract affiliations from arxiv:affiliation elements
            affiliations = [
                aff.text.strip()
                for a in entry.findall("atom:author", _NS)
                for aff in a.findall("arxiv:affiliation", _NS)
                if aff.text
            ]
            raw_affiliation = "; ".join(affiliations) or self.institution_name

            # SC gate — only count papers the storage pipeline will keep, so the
            # crawl keeps paginating until `target` real SC papers are found.
            if sc_score_of(title, abstract) <= 0.0:
                continue

            self._accepted += 1
            yield {
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

        # Pagination
        total_text = root.findtext("opensearch:totalResults", "0", _NS) or "0"
        total = int(total_text) if total_text.isdigit() else 0
        query = response.meta.get("query", "")
        start = response.meta.get("start", 0)
        next_start = start + _BATCH
        if next_start < min(total, 500) and self._accepted < self.target_limit:
            yield scrapy.Request(
                self._build_url(query, next_start),
                callback=self.parse,
                meta={"query": query, "start": next_start},
            )
