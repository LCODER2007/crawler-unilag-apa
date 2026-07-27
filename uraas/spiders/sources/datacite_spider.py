import os
import sys
import urllib.parse

import scrapy

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin


class DataCiteSpider(DedupAwareSpiderMixin, scrapy.Spider):
    """Harvest DOIs registered with DataCite for an institution.

    DataCite's public search API requires no auth key. Despite the module's
    original assumption that these are "datasets/software, not papers", a
    live 25-record sample of the plain ROR-wave query (2026-07-18) was 44%
    Text/JournalArticle and only 24% actually Dataset — every record's real
    `attributes.types.resourceTypeGeneral` is used instead of a blanket
    "dataset" (see _resource_type_to_content_type()) so real journal-article/
    text DOIs stop being silently relabeled as datasets in storage.
    """

    name = "datacite_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
        "USER_AGENT": (
            f"URAAS/1.0 (+https://github.com; mailto:{config.OPENALEX_MAILTO})"
        ),
    }

    # DataCite Metadata Schema resourceTypeGeneral controlled vocabulary ->
    # the pipeline's expected lowercase/spaced form (matches _type_map in
    # uraas/pipelines/database.py). Anything not listed here falls through
    # unmapped rather than being mislabeled.
    _RESOURCE_TYPE_MAP = {
        "dataset": "dataset",
        "software": "dataset",
        "journalarticle": "journal article",
        "conferencepaper": "conference paper",
        "conferenceproceeding": "conference paper",
        "bookchapter": "book chapter",
        "book": "article",
        "dissertation": "thesis",
        "report": "report",
        "preprint": "preprint",
        "text": "article",
        "datapaper": "article",
    }

    PAGE_SIZE = 25

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
        boost_special: fan out extra DataCite queries seeded with SC keywords
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

        self.logger.info(f"Initialized DataCite spider for {self.institution_name}")
        self.logger.info(
            f"ROR ID: {self.ror_id}  | boost_special={self.boost_special} | sc_only={self.sc_only} | target={self.target_limit}"
        )
        self._init_dedup_index()

    def _build_url(self, *, extra_query: str = "") -> str:
        aff_clause = f'creators.affiliation.name:"{self.institution_name}"'
        query = f"{aff_clause} AND ({extra_query})" if extra_query else aff_clause
        return (
            "https://api.datacite.org/dois"
            f"?query={urllib.parse.quote(query)}"
            f"&page[size]={self.PAGE_SIZE}&page[cursor]=1"
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
                url=url,
                callback=self.parse,
                meta={"wave": "ror", "query": "", "scanned_this_wave": 0},
            )

        # Wave 2 — one fan-out request per SC seed phrase, AND-ed with affiliation.
        if self.boost_special:
            for seed in SC_SEED_KEYWORDS:
                url = self._build_url(extra_query=seed)
                self.logger.debug(f"[SC wave seed={seed!r}] {url}")
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta={"wave": f"sc:{seed}", "query": seed, "scanned_this_wave": 0},
                )

    def parse(self, response):
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        try:
            data = response.json()
        except Exception as e:
            self.logger.warning(f"DataCite JSON parse failed: {e}")
            return

        entries = data.get("data", [])
        wave = response.meta.get("wave", "ror")
        self.logger.info(f"[{wave}] received {len(entries)} DOIs")

        scanned_this_wave = response.meta.get("scanned_this_wave", 0)

        for entry in entries:
            if self._accepted >= self.target_limit:
                break
            if scanned_this_wave >= self.max_results_scanned:
                break
            scanned_this_wave += 1

            attrs = entry.get("attributes", {})
            titles = attrs.get("titles") or []
            title = (titles[0].get("title", "") if titles else "").strip()
            if not title:
                continue

            doi = attrs.get("doi", "")
            url = attrs.get("url") or (f"https://doi.org/{doi}" if doi else "")

            abstract = ""
            for d in attrs.get("descriptions", []) or []:
                if d.get("descriptionType") == "Abstract":
                    abstract = d.get("description", "")
                    break

            creators = attrs.get("creators") or []
            authors_full = [
                {"name": c.get("name", ""), "orcid": "", "ror": ""}
                for c in creators
                if c.get("name")
            ]

            # affiliation entries are inconsistently typed across DataCite
            # DOI registrants: plain strings for most, {"name": ...} dicts
            # (sometimes with a ROR-linked affiliationIdentifier) for others.
            raw_affs = []
            for c in creators:
                for aff in (c.get("affiliation") or []):
                    if isinstance(aff, str):
                        if aff:
                            raw_affs.append(aff)
                    elif isinstance(aff, dict) and aff.get("name"):
                        raw_affs.append(aff["name"])

            if raw_affs:
                aff_text = " ".join(raw_affs)
                if not self.institution_config.matches_affiliation(aff_text):
                    self._rejected_aff += 1
                    self.logger.debug(f"DataCite aff FAIL: {title[:60]}")
                    continue
            else:
                # Live-tested 2026-07-19: essentially never happens (0/25 on
                # a real sample — the creators.affiliation.name: query
                # already restricts to structured-affiliation matches), but
                # when it does, fall back to a text match instead of
                # trusting the query blind — same belt-and-suspenders
                # pattern as core_spider.py/openaire_spider.py.
                combined = f"{title} {abstract}".lower()
                if not any(
                    p.lower() in combined for p in self.institution_config.affiliation_patterns
                ):
                    self._rejected_aff += 1
                    continue

            if sc_score_of(title, abstract) <= 0.0:
                continue

            # Dedup gate — skip (don't count, but keep paginating past) records
            # already in the DB.
            if self._is_known(doi=doi, url=url, title=title):
                continue

            pub_year = attrs.get("publicationYear") or ""
            pub_date = str(pub_year) if pub_year else str(attrs.get("registered") or "")[:10]

            resource_type_general = (
                (attrs.get("types") or {}).get("resourceTypeGeneral") or ""
            ).lower()
            content_type = self._RESOURCE_TYPE_MAP.get(resource_type_general, resource_type_general or "dataset")

            self._accepted += 1
            item = {
                "title": title,
                "authors_full": authors_full,
                "abstract": abstract,
                "doi": doi,
                "url": url,
                "pdf_url": None,
                "publication_date": pub_date,
                "content_type": content_type,
                "source_repository": "DataCite",
                "is_unilag_author": True,
                "raw_affiliation": " | ".join(raw_affs) if raw_affs else self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
            }
            yield item
            self._mark_seen(doi=doi, url=url, title=title)

        next_link = (data.get("links") or {}).get("next")
        if (
            next_link
            and self._accepted < self.target_limit
            and scanned_this_wave < self.max_results_scanned
        ):
            wave = response.meta.get("wave", "ror")
            query = response.meta.get("query", "")
            yield scrapy.Request(
                url=next_link,
                callback=self.parse,
                meta={"wave": wave, "query": query, "scanned_this_wave": scanned_this_wave},
            )

    def closed(self, reason):
        self.logger.info(
            f"DataCite spider closed | {self.institution_name} | "
            f"accepted={self._accepted} | rejected_aff={self._rejected_aff} | "
            f"skipped_known={self._skipped_known} | reason={reason}"
        )
