"""
OpenAIRE spider — queries the OpenAIRE Graph API.

OpenAIRE aggregates research from EU-funded projects, repositories across 150+
countries, and African research networks (NREN partnerships, African university
repositories). Particularly strong for:
  • African development research
  • Research from Nigerian/West African institutions
  • Open access preprints and technical reports not in OpenAlex

Free API, no key required. Rate limit: 7200 req/hour.
Docs: graph.openaire.eu/docs/apis/
"""

import os
import sys
from urllib.parse import urlencode

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

# Graph API v1 — old search/publications v2 returns 400 for keyword+affiliation combos
_BASE = "https://api.openaire.eu/graph/v1/researchProducts"


class OpenAIRESpider(DedupAwareSpiderMixin, scrapy.Spider):
    name = "openaire"
    custom_settings = {
        "DOWNLOAD_DELAY": 0.6,
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

    def _text_affiliation_match(self, title: str, abstract: str) -> bool:
        """OpenAIRE's researchProducts authors[] carries no affiliation field
        at all (live-verified: 0/50 sampled records exposed one), and the
        free-text `search=` query is relevance-ranked, not a guaranteed
        phrase filter, so a hit isn't necessarily institution-authored. Same
        belt-and-suspenders text-match fallback as core_spider.py/
        semantic_scholar_spider.py use for the same reason — a real but
        bounded false-positive risk, preferable to accepting everything
        unconditionally (the prior behavior)."""
        combined = f"{title} {abstract}".lower()
        return any(p.lower() in combined for p in self._affiliation_patterns)

    def _build_url(self, search: str, page: int = 1) -> str:
        params = {
            "type": "publication",
            "search": search,
            "page": page,
            "pageSize": 50,
        }
        return f"{_BASE}?{urlencode(params)}"

    async def start(self):
        if not self.sc_only:
            yield scrapy.Request(
                self._build_url(f'"{self.institution_name}"'),
                callback=self.parse,
                meta={"search": f'"{self.institution_name}"', "page": 1},
            )
        if self.boost_special:
            priority_seeds = [
                s
                for s in SC_SEED_KEYWORDS
                if any(
                    k in s
                    for k in (
                        "indigenous",
                        "cultural",
                        "postcolonial",
                        "oral",
                        "decolonial",
                        "ubuntu",
                    )
                )
            ]
            for seed in priority_seeds:
                search = f'"{self.institution_name}" "{seed}"'
                yield scrapy.Request(
                    self._build_url(search),
                    callback=self.parse,
                    meta={"search": search, "page": 1},
                    priority=10,
                )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()
        data = response.json()
        results = data.get("results") or []
        if not isinstance(results, list):
            results = []

        for r in results:
            if self._accepted >= self.target_limit:
                return

            title = (r.get("title") or r.get("mainTitle") or "").strip()
            if not title:
                continue

            # The real OpenAIRE Graph API v1 field is "descriptions" (plural,
            # a list) — "description" (singular) does not exist in live
            # responses, so this was always falling through to "" and every
            # OpenAIRE-sourced item was stored with a blank abstract (also
            # starving sc_score_of() of half its input text). Handle both
            # spellings/shapes defensively since the exact schema isn't
            # formally versioned in the docs.
            desc = r.get("descriptions") or r.get("description") or ""
            abstract = (
                desc
                if isinstance(desc, str)
                else " ".join(desc) if isinstance(desc, list) else ""
            ).strip()

            # DOI from pids list
            doi = ""
            for pid in r.get("pids") or []:
                if isinstance(pid, dict) and pid.get("scheme", "").lower() == "doi":
                    doi = pid.get("value", "")
                    break

            authors_raw = r.get("authors") or []
            authors = [
                (a.get("fullName") or a.get("fullname") or "").strip()
                for a in authors_raw
                if isinstance(a, dict)
            ]
            authors = [a for a in authors if a]

            year = str(r.get("publicationYear") or r.get("publicationDate") or "")[:4]
            url_val = f"https://doi.org/{doi}" if doi else ""

            # Cross-check author names against the verified staff roster
            # first — a materially stronger, independent signal than a
            # title/abstract text mention — falling back to the text match
            # for genuine staff not yet in our harvested roster.
            roster_ok = self.institution_config.matches_staff_roster(authors)
            if not roster_ok and not self._text_affiliation_match(title, abstract):
                continue

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
                "pdf_url": None,
                "publication_date": year,
                "source_repository": "OpenAIRE",
                "is_unilag_author": True,
                "raw_affiliation": self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                # "strong" only via the staff-roster cross-check — OpenAIRE
                # carries no author affiliation field to check instead.
                "affiliation_confidence": "strong" if roster_ok else "weak",
            }
            yield item
            self._mark_seen(doi=doi, url=url_val, title=title)

        total = int(data.get("header", {}).get("numFound") or 0)
        page = response.meta.get("page", 1)
        search = response.meta.get("search", "")
        if (
            page * 50 < min(total, self.max_results_scanned)
            and self._accepted < self.target_limit
        ):
            yield scrapy.Request(
                self._build_url(search, page + 1),
                callback=self.parse,
                meta={"search": search, "page": page + 1},
            )
