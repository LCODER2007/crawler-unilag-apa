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
import re
import sys
from urllib.parse import urlencode, urljoin

import scrapy
from scrapy.http import Request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

# OJS 3.x — old index.php/ajol/search/results path 404s; the current live
# search form (verified against the site) posts to index.php/ajol/search/search.
# A bare /search/search (no index.php/ajol prefix) 302-redirects to the
# homepage regardless of query, so every request collapses to one dupefiltered URL.
_SEARCH_BASE = "https://www.ajol.info/index.php/ajol/search/search"
_DOI_RE = re.compile(r"10\.\d{4,}/\S+")
_SC_SEEDS = [
    "indigenous knowledge",
    "cultural heritage",
    "african literature",
    "oral tradition",
    "ethnobotany",
    "traditional medicine",
    "postcolonial",
    "yoruba",
    "igbo",
    "hausa",
    "nigeria",
    "west africa",
]


class AJOLSpider(DedupAwareSpiderMixin, scrapy.Spider):
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
            sc_only.lower() in _truthy if isinstance(sc_only, str) else bool(sc_only)
        )
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0
        self._seen_urls: set = set()
        self._init_dedup_index()

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
            "orderBy": "relevance",
            "sort": "newest",
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
                self._build_url(q),
                callback=self.parse_list,
                meta={"query": q, "page": 1},
            )

        if self.boost_special:
            for seed in _SC_SEEDS[:8]:
                q = f'"{seed}"'
                if q not in seen_queries:
                    seen_queries.add(q)
                    yield Request(
                        self._build_url(q),
                        callback=self.parse_list,
                        meta={"query": q, "page": 1},
                        priority=5,
                    )

    def parse_list(self, response):
        if response.status in (403, 429):
            self.logger.warning(
                f"AJOL blocked ({response.status}) — skipping: {response.url[:80]}"
            )
            return
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        # Each result is a div with class "article-summary" (verified against
        # the live markup — note hyphen, not underscore).
        results = response.css("div.article-summary, li.article, .search-result")
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
            if (
                "/article/view/" not in full_url
                and "/article/download/" not in full_url
            ):
                continue
            if full_url in self._seen_urls:
                continue
            self._seen_urls.add(full_url)
            title = item.css("a::text").get("").strip()
            # The listing card already has the full comma-separated author
            # string (div.meta div.authors) — simpler and more reliable than
            # the article detail page's per-author markup, so grab it here
            # and pass it through rather than re-deriving it per-article.
            authors_str = item.css("div.meta div.authors::text").get("") or ""
            listing_authors = [a.strip() for a in authors_str.split(",") if a.strip()]
            yield Request(
                full_url,
                callback=self.parse_article,
                meta={
                    "title": title,
                    "url": full_url,
                    "listing_authors": listing_authors,
                },
            )

        # Pagination — AJOL's own `page=N` query param is silently ignored
        # (confirmed live: page=1 vs page=2 return byte-identical results),
        # and the `a.next`/`a[rel=next]` selectors never match anything on
        # live pages either. The real mechanism is a `searchPage=N` param
        # embedded in a `<select name="paging">` widget's option values —
        # follow that option's href directly instead of guessing the URL
        # shape, since AJOL's full query string (searchJournal, orderBy,
        # date-range fields, etc.) isn't reproducible by hand reliably.
        page = response.meta.get("page", 1)
        query = response.meta.get("query", "")
        next_page_href = response.xpath(
            f'//select[@name="paging"]/option[normalize-space(text())="{page + 1}"]/@value'
        ).get()
        # A same-page-number option's value is just the literal page number
        # (no href) — only follow it if it's an actual URL (i.e. any later page).
        if (
            next_page_href
            and next_page_href.startswith("http")
            and self._accepted < self.target_limit
        ):
            yield Request(
                next_page_href,
                callback=self.parse_list,
                meta={"query": query, "page": page + 1},
            )

    def parse_article(self, response):
        """Extract metadata from an AJOL article detail page (OJS-based)."""
        if response.status in (403, 429):
            self.logger.warning(
                f"AJOL blocked ({response.status}) on article — skipping"
            )
            return
        # h1.page-title/.article-title/h3.title never match live pages — the
        # real heading is h1.page-header (live-verified 2026-07-18). Keep the
        # old selectors as a harmless fallback chain in case AJOL varies by
        # journal template, but the listing-page title (already known-good,
        # passed via meta) is checked first since it's the one selector that
        # was actually confirmed reliable across searches.
        title = (
            response.meta.get("title", "")
            or response.css(
                "h1.page-header::text, h1.page-title::text, "
                "h1.article-title::text, h3.title::text"
            ).get("")
        ).strip()
        if not title:
            return

        # Needs the descendant combinator ("p ::text", space before ::text) —
        # abstract text on live pages sits inside nested <em>/<i> tags, and
        # "p::text" (no space) only grabs direct child text nodes so it
        # returns nothing whenever any inline formatting wraps the text.
        # Real class is "article-abstract", not "abstract".
        abstract = " ".join(
            response.css(
                "div.article-abstract p ::text, div.abstract p ::text, "
                "section.abstract p ::text, #articleAbstract p ::text, "
                ".abstractSection p ::text"
            ).getall()
        ).strip()

        # Prefer the author string already captured from the search-listing
        # card (comma-separated, confirmed reliable) — the detail page's own
        # markup needs a different, more specific selector per journal
        # template and duplicating that per-article is unnecessary when the
        # listing already has it.
        authors = response.meta.get("listing_authors") or []
        if not authors:
            authors = response.css(
                "div.authors div.author h5::text, div.authors span::text, "
                "ul.authors li span.name::text, .author-string-href::text"
            ).getall()
            authors = [a.strip() for a in authors if a.strip()]

        # DOI — look for the canonical DOI link or meta tag
        doi = (
            response.css("meta[name='DC.Identifier.DOI']::attr(content)").get()
            or response.css("a[href*='doi.org']::text").re_first(r"10\.\d{4,}/\S+")
            or ""
        ).strip()

        pdf_url = response.css(
            "a.pdf::attr(href), a[href*='download']::attr(href)"
        ).get()
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
        affil_strong = any(term in affil_text for term in self._affil_terms)
        matches = affil_strong
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

        item_url = response.meta.get("url", response.url)

        # Dedup gate — skip papers already in the DB.
        if self._is_known(doi=doi, url=item_url, title=title):
            return

        self._accepted += 1
        item = {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "doi": doi or None,
            "url": item_url,
            "pdf_url": pdf_url,
            "publication_date": pub_date[:10] if pub_date else "",
            "source_repository": "AJOL",
            "is_unilag_author": True,
            "raw_affiliation": affil_text[:500] or self.institution_name,
            "institution": self.institution_name,
            "institution_ror": self.ror_id,
            # "strong" only when AJOL's own structured affiliation
            # field/meta tag named the institution — the whole-page-text
            # fallback can't distinguish authored-there from written-about.
            "affiliation_confidence": "strong" if affil_strong else "weak",
        }
        yield item
        self._mark_seen(doi=doi, url=item_url, title=title)

    def closed(self, reason):
        self.logger.info(
            f"AJOL spider closed | {self.institution_name} | "
            f"accepted={self._accepted} | skipped_known={self._skipped_known} | reason={reason}"
        )
