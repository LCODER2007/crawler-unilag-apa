"""
DOAJ spider — Directory of Open Access Journals API v3.

DOAJ indexes 20,000+ OA journals and is particularly strong for African
humanities, social sciences, and indigenous knowledge journals. Many
AJOL-listed journals appear in DOAJ.

Free API, no key required. Docs: doaj.org/api/v3/docs
Rate limit: 60 req/min — we use 1.5s delay.
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

_BASE = "https://doaj.org/api/v3/search/articles"
_SC_AFFINITY = {
    "indigenous", "cultural", "traditional", "oral", "heritage",
    "african", "yoruba", "igbo", "hausa", "postcolonial",
}


class DOAJSpider(DedupAwareSpiderMixin, scrapy.Spider):
    name = "doaj"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS": 1,
        "USER_AGENT": f"URAAS/1.0 (+SC discovery; mailto:{config.OPENALEX_MAILTO})",
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
        self.max_results_scanned = config.MAX_RESULTS_SCANNED
        self._init_dedup_index()

    def _build_url(self, query: str, page: int = 1) -> str:
        # DOAJ v3: query is a path segment, must be URL-encoded.
        # Avoid field:value syntax — DOAJ rejects compound field queries (400).
        # Free-text AND/quoted-phrase combos are fine, though (live-verified
        # 2026-07-18: `"University of Lagos" AND "indigenous knowledge"` ->
        # 200, total=3 — see start()).
        # sort must be "field:direction" (e.g. "created_date:desc") — a bare
        # "relevance" value is rejected with a 400 by the current API, so we
        # simply omit sort and take the engine's default relevance ranking.
        encoded_q = quote(query, safe="")
        params = urlencode({"pageSize": 50, "page": page})
        return f"{_BASE}/{encoded_q}?{params}"

    async def start(self):
        seen: set = set()

        if not self.sc_only:
            # Simple affiliation free-text — no field: syntax
            q = f'"{self.institution_name}"'
            seen.add(q)
            yield scrapy.Request(
                self._build_url(q), callback=self.parse,
                meta={"query": q, "page": 1},
            )

        if self.boost_special:
            priority_seeds = [
                s for s in SC_SEED_KEYWORDS
                if any(k in s.lower() for k in _SC_AFFINITY)
            ][:6]
            for seed in priority_seeds:
                # Query institution AND seed together — a keyword-only query
                # was previously used here on the (stale, live-refuted) belief
                # that DOAJ 400s on compound queries. Live-tested: the plain
                # keyword-only wave got 0/50 UNILAG matches on page 1 of 3341
                # total (near-zero yield, up to MAX_RESULTS_SCANNED of wasted
                # scanning per seed), while the compound AND query goes
                # straight to a small, highly-relevant result set (total=3
                # for "indigenous knowledge"). Falls back to keyword-only if
                # the compound form ever does 400 for a given seed.
                q = f'"{self.institution_name}" AND "{seed}"'
                if q not in seen:
                    seen.add(q)
                    yield scrapy.Request(
                        self._build_url(q), callback=self.parse,
                        meta={"query": q, "page": 1, "fallback_seed": seed},
                        priority=5,
                        errback=self._on_compound_query_error,
                    )

    def _on_compound_query_error(self, failure):
        """Fall back to the keyword-only query if DOAJ ever rejects the
        compound institution+seed form for a particular seed (belt-and-
        suspenders — not observed live, but the original code assumed it
        would happen for every seed, so keep a path for it happening for some)."""
        request = failure.request
        seed = request.meta.get("fallback_seed")
        if not seed:
            return
        self.logger.warning(f"DOAJ compound query failed for seed={seed!r}, falling back to keyword-only")
        q = f'"{seed}"'
        yield scrapy.Request(
            self._build_url(q), callback=self.parse,
            meta={"query": q, "page": 1}, priority=5,
        )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()
        try:
            data = response.json()
        except Exception:
            self.logger.warning(f"DOAJ JSON parse error: {response.url[:120]}")
            return

        inst_lower = self.institution_name.lower()

        for r in data.get("results", []):
            if self._accepted >= self.target_limit:
                return
            bib = r.get("bibjson", {})
            title = (bib.get("title") or "").strip()
            if not title:
                continue

            abstract = (bib.get("abstract") or "").strip()

            # Verify institution affiliation via author records
            affil_text = " ".join(
                (a.get("affiliation") or "") for a in bib.get("author", [])
            ).lower()
            if inst_lower not in affil_text and inst_lower not in title.lower() and inst_lower not in abstract.lower():
                continue

            doi = ""
            for ident in bib.get("identifier", []):
                if ident.get("type") == "doi":
                    doi = (ident.get("id") or "").strip()
                    break

            url_val = ""
            for link in bib.get("link", []):
                if link.get("type") in ("fulltext", "article"):
                    url_val = link.get("url", "")
                    break
            if not url_val and doi:
                url_val = f"https://doi.org/{doi}"

            authors = [
                (a.get("name") or "").strip()
                for a in bib.get("author", [])
                if a.get("name")
            ]

            year = str(bib.get("year") or "")
            journal = (bib.get("journal") or {}).get("title", "")

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
                "doi": doi or None,
                "url": url_val or None,
                "pdf_url": None,
                "publication_date": year,
                "source_repository": f"DOAJ/{journal}" if journal else "DOAJ",
                "is_unilag_author": True,
                "raw_affiliation": self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
            }
            yield item
            self._mark_seen(doi=doi, url=url_val, title=title)

        total = int(data.get("total") or 0)
        page = response.meta.get("page", 1)
        query = response.meta.get("query", "")
        if page * 50 < min(total, self.max_results_scanned) and self._accepted < self.target_limit:
            yield scrapy.Request(
                self._build_url(query, page + 1), callback=self.parse,
                meta={"query": query, "page": page + 1},
            )

    def closed(self, reason):
        self.logger.info(
            f"DOAJ spider closed | {self.institution_name} | "
            f"accepted={self._accepted} | skipped_known={self._skipped_known} | reason={reason}"
        )
