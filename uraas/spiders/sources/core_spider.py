"""
CORE spider — queries core.ac.uk (250M+ open-access papers from repos worldwide).

CORE aggregates content from thousands of institutional repositories and OA journals
globally, including many African university repositories. For URAAS it surfaces grey
literature and theses that are not yet indexed by OpenAlex or Crossref.

Requires a free CORE API key: https://core.ac.uk/api-keys/register
Set CORE_API_KEY in .env. Without a key the spider logs a warning and exits.
"""

import os
import sys
from urllib.parse import urlencode, quote

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS

_CORE_BASE = "https://api.core.ac.uk/v3/search/works"


class CORESpider(scrapy.Spider):
    name = "core"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
        "USER_AGENT": f"URAAS/1.0 (+SC discovery; mailto:{config.OPENALEX_MAILTO})",
    }

    def __init__(self, institution="unilag", target=50, boost_special=True, sc_only=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        _truthy = {"1", "true", "yes", "on"}
        self.boost_special = boost_special.lower() in _truthy if isinstance(boost_special, str) else bool(boost_special)
        self.sc_only = sc_only.lower() in _truthy if isinstance(sc_only, str) else bool(sc_only)

        self.api_key = getattr(config, "CORE_API_KEY", "") or os.environ.get("CORE_API_KEY", "")
        if not self.api_key:
            self.logger.warning(
                "CORE_API_KEY not set — CORE spider will not run. "
                "Get a free key at https://core.ac.uk/api-keys/register"
            )

        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def _build_url(self, query: str, offset: int = 0) -> str:
        params = {"q": query, "limit": 100, "offset": offset}
        return f"{_CORE_BASE}?{urlencode(params)}"

    async def start(self):
        if not self.api_key:
            return

        if not self.sc_only:
            url = self._build_url(f'"{self.institution_name}"')
            yield scrapy.Request(url=url, headers=self._headers(), callback=self.parse,
                                 meta={"wave": "general", "query": f'"{self.institution_name}"', "offset": 0})

        if self.boost_special:
            for seed in SC_SEED_KEYWORDS:
                query = f'"{self.institution_name}" "{seed}"'
                url = self._build_url(query)
                yield scrapy.Request(url=url, headers=self._headers(), callback=self.parse,
                                     meta={"wave": f"sc:{seed}", "query": query, "offset": 0}, priority=10)

    def parse(self, response):
        if self._accepted >= self.target_limit:
            return
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
            authors = [a.get("name", "") for a in (r.get("authors") or []) if a.get("name")]
            abstract = (r.get("abstract") or "").strip()
            pub_year = r.get("yearPublished") or ""
            url_val = r.get("sourceFulltextUrls", [None])[0] or (f"https://doi.org/{doi}" if doi else "")
            pdf_url = r.get("downloadUrl") or None
            doc_type = r.get("documentType") or ""

            self._accepted += 1
            yield {
                "title": title, "abstract": abstract, "authors": authors, "doi": doi,
                "url": url_val, "pdf_url": pdf_url, "publication_date": str(pub_year),
                "source_repository": "CORE", "is_unilag_author": True,
                "raw_affiliation": self.institution_name, "institution": self.institution_name,
                "institution_ror": self.ror_id, "content_type": doc_type,
            }

        offset = response.meta.get("offset", 0) + 100
        total = data.get("totalHits", 0)
        if offset < min(total, 500) and self._accepted < self.target_limit:
            query = response.meta["query"]
            next_url = self._build_url(query, offset)
            yield scrapy.Request(url=next_url, headers=self._headers(), callback=self.parse,
                                 meta={"wave": wave, "query": query, "offset": offset})
