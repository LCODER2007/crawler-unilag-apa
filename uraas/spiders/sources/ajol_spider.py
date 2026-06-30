"""
AJOL spider — African Journals Online (ajol.info).

AJOL is the most important African-specific journal aggregator, hosting
2,000+ peer-reviewed journals from 40+ African countries. It is the
primary source for Nigerian humanities, social sciences, law, and
indigenous knowledge research not indexed in OpenAlex or Crossref.

Uses AJOL's search endpoint and parses the HTML results. The site
structure is stable (OJS-based); falling back to OAI-PMH harvest is
possible but much slower without affiliation filtering.

No API key needed. Rate limit: polite 2s delay.
"""

import os
import sys
import re
from urllib.parse import urlencode, urljoin

import scrapy
from scrapy.http import Request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.utils.ai_classifier import sc_score_of

_SEARCH_BASE = "https://www.ajol.info/index.php/ajol/search/results"
_DOI_RE = re.compile(r"10\.\d{4,}/\S+")
_SC_SEEDS = [
    "indigenous knowledge", "cultural heritage", "african literature",
    "oral tradition", "ethnobotany", "traditional medicine", "postcolonial",
    "yoruba", "igbo", "hausa", "nigeria", "west africa",
]


class AJOLSpider(scrapy.Spider):
    name = "ajol"
    allowed_domains = ["www.ajol.info"]
    custom_settings = {
        "DOWNLOAD_DELAY": 2.5,
        "CONCURRENT_REQUESTS": 1,
        # AJOL blocks non-browser UAs; mimic a real browser to avoid 403.
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.ajol.info/",
        },
        "HTTPERROR_ALLOWED_CODES": [403, 429],
    }

    def __init__(
        self, institution="unilag", target=50, boost_special=True, sc_only=False,
        *args, **kwargs,
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
            raise ValueError(f"Institution '{institution}' not found")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0
        self._seen_urls: set = set()

        # Build short affiliation terms for matching
        name_parts = self.institution_name.lower().split()
        self._affil_terms = [self.institution_name.lower()]
        if "university" in name_parts:
            idx = name_parts.index("university")
            if idx > 0:
                self._affil_terms.append(name_parts[idx - 1])  # e.g. "lagos"

    def _build_url(self, query: str, page: int = 1) -> str:
        params = {
            "query": query,
            "searchField": "query",
            "orderBy": "score",
            "sort": "",
            "limit": 20,
            "page": page,
        }
        return f"{_SEARCH_BASE}?{urlencode(params)}"

    async def start(self):
        seen_queries: set = set()

        if not self.sc_only:
            q = f'"{self.institution_name}"'
            seen_queries.add(q)
            yield Request(
                self._build_url(q), callback=self.parse_list,
                meta={"query": q, "page": 1},
            )

        if self.boost_special:
            for seed in _SC_SEEDS[:8]:
                q = f'"{seed}"'
                if q not in seen_queries:
                    seen_queries.add(q)
                    yield Request(
                        self._build_url(q), callback=self.parse_list,
                        meta={"query": q, "page": 1}, priority=5,
                    )

    def parse_list(self, response):
        if response.status in (403, 429):
            self.logger.warning(f"AJOL blocked ({response.status}) — skipping: {response.url[:80]}")
            return
        if self._accepted >= self.target_limit:
            return

        # Each result is a div with class "result" or "article_summary"
        # AJOL uses OJS — the search results page lists article titles with links
        results = response.css("div.article_summary, li.article, .search-result")
        if not results:
            # Fallback: any heading-linked article
            results = response.css("h4 a, h3 a, .result a")

        for item in results:
            if self._accepted >= self.target_limit:
                return
            link = item.css("a::attr(href)").get() or item.attrib.get("href", "")
            if not link:
                continue
            full_url = urljoin(response.url, link)
            if "/article/view/" not in full_url and "/article/download/" not in full_url:
                continue
            if full_url in self._seen_urls:
                continue
            self._seen_urls.add(full_url)
            title = item.css("a::text").get("").strip()
            yield Request(
                full_url, callback=self.parse_article,
                meta={"title": title, "url": full_url},
            )

        # Pagination
        page = response.meta.get("page", 1)
        query = response.meta.get("query", "")
        next_link = response.css("a.next::attr(href), a[rel=next]::attr(href)").get()
        if next_link and self._accepted < self.target_limit:
            yield Request(
                urljoin(response.url, next_link), callback=self.parse_list,
                meta={"query": query, "page": page + 1},
            )
        elif page < 5 and self._accepted < self.target_limit and results:
            # Fallback numeric pagination
            yield Request(
                self._build_url(query, page + 1), callback=self.parse_list,
                meta={"query": query, "page": page + 1},
            )

    def parse_article(self, response):
        """Extract metadata from an AJOL article detail page (OJS-based)."""
        if response.status in (403, 429):
            self.logger.warning(f"AJOL blocked ({response.status}) on article — skipping")
            return
        title = (
            response.css("h1.page-title::text, h1.article-title::text, h3.title::text").get("")
            or response.meta.get("title", "")
        ).strip()
        if not title:
            return

        abstract = " ".join(
            response.css(
                "div.abstract p::text, section.abstract p::text, "
                "#articleAbstract p::text, .abstractSection p::text"
            ).getall()
        ).strip()

        authors = response.css(
            "div.authors span::text, ul.authors li span.name::text, "
            ".author-string-href::text"
        ).getall()
        authors = [a.strip() for a in authors if a.strip()]

        # DOI — look for the canonical DOI link or meta tag
        doi = (
            response.css("meta[name='DC.Identifier.DOI']::attr(content)").get()
            or response.css("a[href*='doi.org']::text").re_first(r"10\.\d{4,}/\S+")
            or ""
        ).strip()

        pdf_url = (
            response.css("a.pdf::attr(href), a[href*='download']::attr(href)").get()
        )
        if pdf_url:
            pdf_url = urljoin(response.url, pdf_url)

        pub_date = (
            response.css("meta[name='DC.Date.issued']::attr(content)").get()
            or response.css(".published::text, .date::text").re_first(r"\d{4}")
            or ""
        )

        affil_text = " ".join(
            response.css(
                ".affiliations::text, .author-affiliation::text, meta[name='citation_author_institution']::attr(content)"
            ).getall()
        ).lower()

        # Only yield if the affiliation matches our institution
        matches = any(term in affil_text for term in self._affil_terms)
        if not matches:
            # If abstract/body text mentions the institution, still accept
            page_text = response.text.lower()
            matches = any(term in page_text for term in self._affil_terms)

        if not matches:
            return

        # SC gate — only count papers the storage pipeline will keep, so the
        # crawl keeps following links until `target` real SC papers are found.
        if sc_score_of(title, abstract) <= 0.0:
            return

        self._accepted += 1
        yield {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "doi": doi or None,
            "url": response.meta.get("url", response.url),
            "pdf_url": pdf_url,
            "publication_date": pub_date[:10] if pub_date else "",
            "source_repository": "AJOL",
            "is_unilag_author": True,
            "raw_affiliation": affil_text[:500] or self.institution_name,
            "institution": self.institution_name,
            "institution_ror": self.ror_id,
        }
