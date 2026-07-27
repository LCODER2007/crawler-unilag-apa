import os
import sys

import scrapy

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin


class CrossrefSpider(DedupAwareSpiderMixin, scrapy.Spider):
    name = "crossref_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        # Crossref etiquette: identify the bot + a contact so we land in the
        # "polite pool" (https://www.crossref.org/documentation/retrieve-metadata/rest-api/).
        "USER_AGENT": (
            f"URAAS/1.0 (+https://github.com; mailto:{config.OPENALEX_MAILTO})"
        ),
    }

    SELECT_FIELDS = "DOI,title,abstract,author,issued,URL,link,funder"

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

        registry = get_registry()
        self.institution_config = registry.get(institution)

        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0
        self._rejected_aff = 0
        self.max_results_scanned = config.MAX_RESULTS_SCANNED

        self.logger.info(f"Initialized Crossref spider for {self.institution_name}")
        self.logger.info(
            f"ROR ID: {self.ror_id}  | boost_special={self.boost_special} | sc_only={self.sc_only} | target={self.target_limit}"
        )
        self._init_dedup_index()

    def _build_url(self, *, query: str = "", offset: int = 0) -> str:
        import urllib.parse

        encoded_name = urllib.parse.quote(self.institution_name)
        q = f"&query={urllib.parse.quote(query)}" if query else ""
        mailto = urllib.parse.quote(config.OPENALEX_MAILTO)
        return (
            f"https://api.crossref.org/works"
            f"?query.affiliation={encoded_name}"
            f"{q}"
            f"&select={self.SELECT_FIELDS}"
            f"&rows=50&offset={offset}"
            f"&mailto={mailto}"
        )

    async def start(self):
        # Wave 1 — plain affiliation query
        if not self.sc_only:
            url = self._build_url()
            # DEBUG not INFO — with 300+ SC seed waves, logging every raw
            # query URL at INFO level floods the dashboard's live feed
            # (which runs at LOG_LEVEL=INFO) with unreadable noise; still
            # available for real debugging via LOG_LEVEL=DEBUG.
            self.logger.debug(f"[ROR wave] {url}")
            yield scrapy.Request(
                url=url, callback=self.parse, meta={"wave": "ror", "query": "", "offset": 0}
            )

        # Wave 2 — one fan-out request per SC seed phrase, AND-ed with affiliation.
        if self.boost_special:
            for seed in SC_SEED_KEYWORDS:
                url = self._build_url(query=seed)
                self.logger.debug(f"[SC wave seed={seed!r}] {url}")
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta={"wave": f"sc:{seed}", "query": seed, "offset": 0},
                )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        data = response.json()
        items = data.get("message", {}).get("items", [])
        wave = response.meta.get("wave", "ror")
        self.logger.info(f"[{wave}] received {len(items)} works")

        for work in items:
            if self._accepted >= self.target_limit:
                break

            title = work.get("title", [""])[0] if work.get("title") else ""
            if not title:
                continue

            doi = work.get("DOI", "")
            url = work.get("URL", "")
            abstract = work.get("abstract", "")

            # Affiliation check using Crossref author.affiliation field.
            # Crossref returns affiliation data when available; if empty we
            # accept the paper (institution filter on the query is still active).
            raw_affs = []
            authors = []
            for author in work.get("author", []):
                given = author.get("given", "")
                family = author.get("family", "")
                if given or family:
                    authors.append(f"{given} {family}".strip())
                for aff in author.get("affiliation", []):
                    name = aff.get("name", "")
                    if name:
                        raw_affs.append(name)

            if raw_affs:
                aff_text = " ".join(raw_affs)
                if not self.institution_config.matches_affiliation(aff_text):
                    self._rejected_aff += 1
                    self.logger.debug(f"Crossref aff FAIL: {title[:60]}")
                    continue

            # SC gate — only count papers the storage pipeline will keep, so the
            # crawl keeps paginating until `target` real SC papers are found.
            if sc_score_of(title, abstract) <= 0.0:
                continue

            # Dedup gate — skip (don't count, but keep paginating past) papers
            # already in the DB, so repeat crawls make real progress instead
            # of re-filling target with the same deterministic top results.
            if self._is_known(doi=doi, url=url, title=title):
                continue

            # Try to find a PDF link in the 'link' array if open access
            pdf_url = None
            for link in work.get("link", []):
                if link.get("content-type") == "application/pdf":
                    pdf_url = link.get("URL")
                    break

            # Crossref funder data uses Funder Registry DOIs (10.13039/...),
            # not ROR — no ror field to map, unlike OpenAlex.
            funders = []
            for f in work.get("funder", []) or []:
                name = f.get("name", "")
                if not name:
                    continue
                awards = [a for a in (f.get("award") or []) if a]
                funders.append({
                    "name": name,
                    "ror": None,
                    "award_id": ", ".join(awards) if awards else None,
                    "funder_doi": f.get("DOI") or None,
                })

            self._accepted += 1
            item = {
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "doi": doi,
                "url": url,
                "pdf_url": pdf_url,
                "source_repository": "Crossref",
                "is_unilag_author": True,
                "raw_affiliation": " | ".join(raw_affs) if raw_affs else self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                "funders": funders,
            }
            yield item
            self._mark_seen(doi=doi, url=url, title=title)

        # Deep pagination — stop when target reached or no more results.
        offset = response.meta.get("offset", 0) + 50
        if (
            items
            and offset < self.max_results_scanned
            and self._accepted < self.target_limit
        ):
            wave = response.meta.get("wave", "ror")
            query = response.meta.get("query", "")
            next_url = self._build_url(query=query, offset=offset)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={"wave": wave, "query": query, "offset": offset},
            )

    def closed(self, reason):
        self.logger.info(
            f"Crossref spider closed | {self.institution_name} | "
            f"accepted={self._accepted} | rejected_aff={self._rejected_aff} | "
            f"skipped_known={self._skipped_known} | reason={reason}"
        )
