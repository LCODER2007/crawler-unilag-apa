"""
CORE spider — queries core.ac.uk (250M+ open-access papers from repos worldwide).

CORE aggregates content from thousands of institutional repositories and OA journals
globally, including many African university repositories. For URAAS it surfaces grey
literature and theses that are not yet indexed by OpenAlex or Crossref.

A free CORE API key (https://core.ac.uk/api-keys/register, set CORE_API_KEY
in .env) raises the rate limit, but live-tested 2026-07-18: the /v3/search/
works endpoint returns full 200 OK results with no Authorization header at
all (only an invalid/garbage key gets 401) — so this now runs keyless with a
lower throughput ceiling rather than refusing to run at all.

Precision note: CORE's `q=` search does NOT do phrase/AND matching the way
`"A" "B"` quoting implies for most search engines — live-verified the quoted
query `"University of Lagos"` returns totalHits=4,482,856 (300x MORE than
the unquoted `University of Lagos`, 14,834), and a completely made-up quoted
phrase returns a comparable multi-million count — quoting provides ~zero
restriction, and CORE's author objects carry no affiliation field at all to
verify against client-side. Since there's no reliable way to confirm a
result is actually institution-affiliated, this spider requires the
institution name to literally appear in the title/abstract text (same
belt-and-suspenders fallback semantic_scholar_spider.py uses for the same
reason) — a real but bounded false-positive risk (a paper merely mentioning
the institution, not authored there), preferable to accepting everything
unconditionally.
"""

import os
import sys
from urllib.parse import quote, urlencode

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

_CORE_BASE = "https://api.core.ac.uk/v3/search/works"


class CORESpider(DedupAwareSpiderMixin, scrapy.Spider):
    name = "core"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
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
            sc_only.lower() in _truthy if isinstance(sc_only, str) else bool(sc_only)
        )

        self.api_key = getattr(config, "CORE_API_KEY", "") or os.environ.get(
            "CORE_API_KEY", ""
        )
        if not self.api_key:
            self.logger.warning(
                "CORE_API_KEY not set — running keyless (lower rate limit). "
                "Get a free key at https://core.ac.uk/api-keys/register for higher throughput."
            )

        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0
        self.max_results_scanned = config.MAX_RESULTS_SCANNED
        self._affiliation_patterns = self.institution_config.affiliation_patterns or [
            self.institution_name
        ]
        self._init_dedup_index()

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_url(self, query: str, offset: int = 0) -> str:
        params = {"q": query, "limit": 100, "offset": offset}
        return f"{_CORE_BASE}?{urlencode(params)}"

    def _text_affiliation_match(self, title: str, abstract: str) -> bool:
        """CORE's author objects carry no affiliation field, and the `q=`
        query itself doesn't reliably restrict to the institution (see
        module docstring) — this is the only verification available."""
        combined = f"{title} {abstract}".lower()
        return any(p.lower() in combined for p in self._affiliation_patterns)

    async def start(self):
        if not self.sc_only:
            url = self._build_url(f'"{self.institution_name}"')
            yield scrapy.Request(
                url=url,
                headers=self._headers(),
                callback=self.parse,
                meta={
                    "wave": "general",
                    "query": f'"{self.institution_name}"',
                    "offset": 0,
                },
            )

        if self.boost_special:
            for seed in SC_SEED_KEYWORDS:
                query = f'"{self.institution_name}" "{seed}"'
                url = self._build_url(query)
                yield scrapy.Request(
                    url=url,
                    headers=self._headers(),
                    callback=self.parse,
                    meta={"wave": f"sc:{seed}", "query": query, "offset": 0},
                    priority=10,
                )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()
        data = response.json()
        results = data.get("results", [])
        wave = response.meta.get("wave", "general")
        self.logger.info("[CORE:%s] received %d results", wave, len(results))

        for r in results:
            if self._accepted >= self.target_limit:
                return
            title = (r.get("title") or "").strip()
            if not title:
                continue
            doi = (r.get("doi") or "").strip()
            authors = [
                a.get("name", "") for a in (r.get("authors") or []) if a.get("name")
            ]
            abstract = (r.get("abstract") or "").strip()
            pub_year = r.get("yearPublished") or ""
            # `.get("sourceFulltextUrls", [None])` only falls back to [None]
            # when the KEY is missing — when CORE returns the key present
            # but as an empty list (common), .get() returns that empty list
            # and [0] raises IndexError, crashing the whole parse() callback
            # for the response (confirmed live 2026-07-19/20: killed CORE
            # mid-crawl, losing every remaining item + the pagination
            # continuation for that response). `or` handles both cases.
            url_val = (r.get("sourceFulltextUrls") or [None])[0] or (
                f"https://doi.org/{doi}" if doi else ""
            )
            pdf_url = r.get("downloadUrl") or None
            doc_type = r.get("documentType") or ""

            # Affiliation gate — see module docstring: CORE's query doesn't
            # reliably restrict to the institution and there's no author
            # affiliation field to check. Cross-check author names against
            # the verified staff roster first (a much stronger, independent
            # signal than title/abstract text mentioning the institution),
            # falling back to the text match for genuine staff not yet in
            # our harvested roster.
            roster_ok = self.institution_config.matches_staff_roster(authors)
            if not roster_ok and not self._text_affiliation_match(title, abstract):
                continue

            # SC gate — only count papers the storage pipeline will keep, so the
            # crawl keeps paginating until `target` real SC papers are found.
            if sc_score_of(title, abstract) <= 0.0:
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
                "publication_date": str(pub_year),
                "source_repository": "CORE",
                "is_unilag_author": True,
                "raw_affiliation": self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                "content_type": doc_type,
                # "strong" only via the staff-roster cross-check — the
                # title/abstract text fallback can't distinguish
                # authored-there from written-about (CORE has no author
                # affiliation field at all to check instead).
                "affiliation_confidence": "strong" if roster_ok else "weak",
            }
            yield item
            self._mark_seen(doi=doi, url=url_val, title=title)

        offset = response.meta.get("offset", 0) + 100
        total = data.get("totalHits", 0)
        if (
            offset < min(total, self.max_results_scanned)
            and self._accepted < self.target_limit
        ):
            query = response.meta["query"]
            next_url = self._build_url(query, offset)
            yield scrapy.Request(
                url=next_url,
                headers=self._headers(),
                callback=self.parse,
                meta={"wave": wave, "query": query, "offset": offset},
            )

    def closed(self, reason):
        self.logger.info(
            "CORE spider closed | %s | accepted=%d | skipped_known=%d | reason=%s",
            self.institution_name,
            self._accepted,
            self._skipped_known,
            reason,
        )
