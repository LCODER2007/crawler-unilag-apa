import os
import sys

import scrapy

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS


class CrossrefSpider(scrapy.Spider):
    name = "crossref_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
    }

    SELECT_FIELDS = "DOI,title,abstract,author,issued,URL,link"

    def __init__(
        self,
        institution="unilag",
        target=20,
        boost_special=True,
        sc_only=False,
        *args,
        **kwargs,
    ):
        """
        boost_special: fan out extra Crossref queries seeded with SC keywords
                       (default True — heavy SC weight).
        sc_only:       skip the plain-affiliation query; crawl only SC-seeded fan-outs.
        """
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        self.boost_special = str(boost_special).lower() not in (
            "false",
            "0",
            "no",
            "off",
        )
        self.sc_only = str(sc_only).lower() in ("true", "1", "yes", "on")

        # Get institution configuration
        registry = get_registry()
        self.institution_config = registry.get(institution)

        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror

        self.logger.info(f"Initialized Crossref spider for {self.institution_name}")
        self.logger.info(
            f"ROR ID: {self.ror_id}  | boost_special={self.boost_special} | sc_only={self.sc_only}"
        )

    def _build_url(self, *, query: str = "", offset: int = 0) -> str:
        import urllib.parse

        encoded_name = urllib.parse.quote(self.institution_name)
        q = f"&query={urllib.parse.quote(query)}" if query else ""
        return (
            f"https://api.crossref.org/works"
            f"?query.affiliation={encoded_name}"
            f"{q}"
            f"&select={self.SELECT_FIELDS}"
            f"&rows=50&offset={offset}"
        )

    def start_requests(self):
        # Wave 1 — plain affiliation query
        if not self.sc_only:
            url = self._build_url()
            self.logger.info(f"[ROR wave] {url}")
            yield scrapy.Request(
                url=url, callback=self.parse, meta={"wave": "ror", "query": ""}
            )

        # Wave 2 — one fan-out request per SC seed phrase, AND-ed with affiliation.
        if self.boost_special:
            for seed in SC_SEED_KEYWORDS:
                url = self._build_url(query=seed)
                self.logger.info(f"[SC wave seed={seed!r}] {url}")
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta={"wave": f"sc:{seed}", "query": seed},
                )

    def parse(self, response):
        data = response.json()
        items = data.get("message", {}).get("items", [])

        for work in items:
            title = work.get("title", [""])[0] if work.get("title") else ""
            doi = work.get("DOI", "")
            url = work.get("URL", "")

            # Abstract might be in abstract or we might not have it
            abstract = work.get("abstract", "")

            # Authors
            authors = []
            for author in work.get("author", []):
                given = author.get("given", "")
                family = author.get("family", "")
                if given or family:
                    authors.append(f"{given} {family}".strip())

            # Try to find a PDF link in the 'link' array if open access
            pdf_url = None
            for link in work.get("link", []):
                if link.get("content-type") == "application/pdf":
                    pdf_url = link.get("URL")
                    break

            yield {
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "doi": doi,
                "url": url,
                "pdf_url": pdf_url,
                "source_repository": "Crossref",
                "is_unilag_author": True,  # Legacy field
                "raw_affiliation": self.institution_name,
                # NEW: Multi-institution support
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
            }

        # Deep pagination — keep the originating wave's query so SC waves don't
        # collapse back into plain-affiliation pagination.
        offset = response.meta.get("offset", 0) + 50
        if items and offset < 500:
            wave = response.meta.get("wave", "ror")
            query = response.meta.get("query", "")
            next_url = self._build_url(query=query, offset=offset)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={"wave": wave, "query": query, "offset": offset},
            )
