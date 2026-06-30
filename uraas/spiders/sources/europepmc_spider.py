"""
EuropePMC spider — queries the Europe PubMed Central REST API.

EuropePMC (europepmc.org) aggregates life-sciences and biomedical literature from
PubMed, PMC, WHO, and many other sources. For URAAS Special Collections it is
particularly valuable for the **Indigenous Knowledge** and **Ethnobotany** subcategories
— traditional plant medicine, ethno-pharmacology, and indigenous health practices
feature heavily in UNILAG research and are well-indexed here.

The API is free, no key required.
"""

import os
import sys
from urllib.parse import urlencode, quote

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.utils.ai_classifier import sc_score_of

_EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PAGE_SIZE = 100


class EuropePMCSpider(scrapy.Spider):
    name = "europepmc"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "USER_AGENT": (
            f"URAAS/1.0 (+read-only SC discovery; mailto:{config.OPENALEX_MAILTO})"
        ),
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

        # Use primary affiliation patterns to widen EPMC search
        self._affiliation_patterns = self.institution_config.affiliation_patterns or [self.institution_name]

        self.logger.info(
            "EuropePMC spider | %s | boost_special=%s | target=%d",
            self.institution_name,
            self.boost_special,
            self.target_limit,
        )

    def _build_url(self, query: str, cursor_mark: str = "*") -> str:
        params = {
            "query": query,
            "format": "json",
            "pageSize": _PAGE_SIZE,
            "resultType": "core",
            "cursorMark": cursor_mark,
        }
        return f"{_EPMC_BASE}?{urlencode(params)}"

    def _affil_query(self, seed: str = "") -> str:
        # EPMC affiliation filter — OR across all known institution name patterns
        affil_parts = " OR ".join(
            f'AFFILIATION:"{p}"' for p in self._affiliation_patterns[:3]
        )
        affil = f"({affil_parts})"
        if seed:
            return f'{affil} AND ("{seed}")'
        return affil

    async def start(self):
        if not self.sc_only:
            url = self._build_url(self._affil_query())
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={"wave": "general", "query": self._affil_query(), "cursor": "*"},
            )

        if self.boost_special:
            # Only run the most SC-relevant seeds for EPMC — ethnobotany, traditional
            # knowledge, and cultural heritage are where EPMC adds the most value.
            priority_seeds = [
                s for s in SC_SEED_KEYWORDS
                if any(k in s.lower() for k in (
                    "indigenous", "traditional", "ethnobotany", "cultural", "oral",
                    "decolonial", "ubuntu", "ethnomusicology",
                ))
            ]
            for seed in priority_seeds:
                query = self._affil_query(seed)
                url = self._build_url(query)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta={"wave": f"sc:{seed}", "query": query, "cursor": "*"},
                    priority=10,
                )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            return

        data = response.json()
        results = data.get("resultList", {}).get("result", [])
        wave = response.meta.get("wave", "general")
        self.logger.info("[EPMC:%s] received %d results", wave, len(results))

        for r in results:
            if self._accepted >= self.target_limit:
                return

            title = (r.get("title") or "").strip().rstrip(".")
            if not title:
                continue

            abstract = (r.get("abstractText") or "").strip()
            doi = (r.get("doi") or "").strip()
            pmid = r.get("pmid") or ""
            pub_date = r.get("firstPublicationDate") or r.get("pubYear") or ""
            doc_type = r.get("pubType") or r.get("source") or ""

            url_val = (
                f"https://doi.org/{doi}" if doi
                else (f"https://europepmc.org/article/med/{pmid}" if pmid else "")
            )
            pdf_url = None
            if r.get("isOpenAccess") == "Y" and r.get("fullTextUrlList"):
                for ft in (r.get("fullTextUrlList", {}).get("fullTextUrl") or []):
                    if ft.get("documentStyle") == "pdf":
                        pdf_url = ft.get("url")
                        break

            authors_raw = r.get("authorList", {}).get("author") or []
            authors = [
                f"{a.get('firstName','')} {a.get('lastName','')}".strip()
                for a in authors_raw
                if a.get("lastName")
            ]

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
                "url": url_val,
                "pdf_url": pdf_url,
                "publication_date": pub_date,
                "source_repository": "EuropePMC",
                "is_unilag_author": True,
                "raw_affiliation": self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                "content_type": doc_type,
            }

        # Cursor-based pagination
        next_cursor = data.get("nextCursorMark")
        hit_count = data.get("hitCount", 0)
        if (
            next_cursor
            and next_cursor != response.meta.get("cursor")
            and results
            and self._accepted < self.target_limit
            and hit_count > _PAGE_SIZE
        ):
            query = response.meta["query"]
            wave = response.meta["wave"]
            next_url = self._build_url(query, next_cursor)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={"wave": wave, "query": query, "cursor": next_cursor},
            )

    def closed(self, reason):
        self.logger.info(
            "EuropePMC spider closed | %s | accepted=%d | reason=%s",
            self.institution_name,
            self._accepted,
            reason,
        )
