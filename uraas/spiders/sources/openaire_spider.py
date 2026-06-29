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

_BASE = "https://api.openaire.eu/search/publications"


class OpenAIRESpider(scrapy.Spider):
    name = "openaire"
    custom_settings = {
        "DOWNLOAD_DELAY": 0.6,
        "CONCURRENT_REQUESTS": 1,
        "USER_AGENT": f"URAAS/1.0 (+SC discovery; mailto:{config.OPENALEX_MAILTO})",
    }

    def __init__(self, institution="unilag", target=50, boost_special=True, sc_only=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        _truthy = {"1", "true", "yes", "on"}
        self.boost_special = boost_special.lower() in _truthy if isinstance(boost_special, str) else bool(boost_special)
        self.sc_only = sc_only.lower() in _truthy if isinstance(sc_only, str) else bool(sc_only)
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0

    def _build_url(self, keywords: str = "", page: int = 1) -> str:
        params = {
            "affiliationORG": self.institution_name,
            "format": "json",
            "size": 50,
            "page": page,
        }
        if keywords:
            params["keywords"] = keywords
        return f"{_BASE}?{urlencode(params)}"

    async def start(self):
        if not self.sc_only:
            yield scrapy.Request(self._build_url(), callback=self.parse,
                                 meta={"keywords": "", "page": 1})
        if self.boost_special:
            priority_seeds = [s for s in SC_SEED_KEYWORDS
                              if any(k in s for k in ("indigenous", "cultural", "postcolonial", "oral", "decolonial", "ubuntu"))]
            for seed in priority_seeds:
                yield scrapy.Request(self._build_url(seed), callback=self.parse,
                                     meta={"keywords": seed, "page": 1}, priority=10)

    def parse(self, response):
        if self._accepted >= self.target_limit:
            return
        data = response.json()
        results = (data.get("response", {}).get("results", {}).get("result") or [])
        if not isinstance(results, list):
            results = [results] if results else []

        for r in results:
            if self._accepted >= self.target_limit:
                return
            metadata = r.get("metadata", {}).get("oaf:entity", {}).get("oaf:result", {})
            title_obj = metadata.get("title", {})
            title = (title_obj if isinstance(title_obj, str) else title_obj.get("$", "")).strip()
            if not title:
                continue

            desc = metadata.get("description", "") or ""
            abstract = (desc if isinstance(desc, str) else desc.get("$", "")).strip()

            pids = metadata.get("pid") or []
            if not isinstance(pids, list):
                pids = [pids]
            doi = ""
            for pid in pids:
                if isinstance(pid, dict) and pid.get("@classid") == "doi":
                    doi = pid.get("$", "")

            creators_raw = metadata.get("creator") or []
            if not isinstance(creators_raw, list):
                creators_raw = [creators_raw]
            authors = [c.get("$", "") if isinstance(c, dict) else str(c) for c in creators_raw if c]

            year = str(metadata.get("dateofacceptance", "") or "")[:4]
            url_val = f"https://doi.org/{doi}" if doi else ""

            self._accepted += 1
            yield {
                "title": title, "abstract": abstract, "authors": authors, "doi": doi,
                "url": url_val, "pdf_url": None, "publication_date": year,
                "source_repository": "OpenAIRE", "is_unilag_author": True,
                "raw_affiliation": self.institution_name, "institution": self.institution_name,
                "institution_ror": self.ror_id,
            }

        # Pagination
        total = int(data.get("response", {}).get("header", {}).get("total", {}).get("$", 0) or 0)
        page = response.meta.get("page", 1)
        keywords = response.meta.get("keywords", "")
        if page * 50 < min(total, 500) and self._accepted < self.target_limit:
            yield scrapy.Request(self._build_url(keywords, page + 1), callback=self.parse,
                                 meta={"keywords": keywords, "page": page + 1})
