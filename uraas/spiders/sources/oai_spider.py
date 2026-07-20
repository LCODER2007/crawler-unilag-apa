"""
Read-only OAI-PMH harvester for an institution's DSpace repository.

Uses ListIdentifiers + GetRecord instead of ListRecords because some DSpace
servers (including UNILAG's) return HTTP 500 on ListRecords while
ListIdentifiers and GetRecord work correctly.

OAI-PMH is read-only by specification — it cannot harm the source repository.
"""

import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import scrapy
from scrapy.selector import Selector

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.african_languages import AFRICAN_LANG_CODES
from uraas.config.institutions import get_registry
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

log = logging.getLogger(__name__)

_MOJIBAKE_RE = re.compile(r"[a-zA-Z]\?|\?[a-zA-Z]")


def _looks_mojibake(text: str) -> bool:
    """A '?' directly adjacent to a letter (no space) is an unusual
    punctuation pattern in real text but exactly what non-ASCII bytes
    replaced with U+FFFD/'?' look like — the signature of UNILAG's OAI-PMH
    encoding bug (see parse_record())."""
    return bool(text) and bool(_MOJIBAKE_RE.search(text))

_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_DEFAULT_LOOKBACK_DAYS = 1825  # ~5 years


class OAISpider(DedupAwareSpiderMixin, scrapy.Spider):
    """Harvest oai_dc metadata using ListIdentifiers + GetRecord.

    UNILAG's DSpace returns 500 on ListRecords but ListIdentifiers and
    GetRecord both work.  This spider paginates ListIdentifiers via
    resumptionToken then fetches each record individually.
    """

    name = "oai_repository"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 2,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1.0,
        "AUTOTHROTTLE_MAX_DELAY": 15.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        "ROBOTSTXT_OBEY": False,
        "USER_AGENT": (
            f"URAAS/1.0 (+read-only OAI-PMH harvester; "
            f"mailto:{config.OPENALEX_MAILTO})"
        ),
        # Allow 500 so we can log it rather than silently ignore
        "HTTPERROR_ALLOWED_CODES": [500],
    }

    def __init__(
        self,
        institution="unilag",
        target=200,
        from_date=None,
        until_date=None,
        oai_set=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)

        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.oai_endpoint = self.institution_config.oai_endpoint
        if not self.oai_endpoint:
            raise ValueError(
                f"Institution '{institution}' has no oai_endpoint configured."
            )

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror

        self.from_date = self._normalize_date(from_date) or self._default_from()
        self.until_date = self._normalize_date(until_date)
        self.oai_set = (
            oai_set
            or getattr(self.institution_config, "oai_set", None)
            or None
        )

        self._accepted = 0
        self._identifiers_fetched = 0

        self.logger.info(
            "OAI harvester | %s | endpoint=%s | from=%s until=%s | set=%s | target=%d",
            self.institution_name,
            self.oai_endpoint,
            self.from_date,
            self.until_date or "(now)",
            self.oai_set or "(all)",
            self.target_limit,
        )
        self._init_dedup_index()

    @staticmethod
    def _normalize_date(value):
        if not value:
            return None
        return str(value).strip()[:10]

    def _default_from(self) -> str:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        return cutoff.strftime("%Y-%m-%d")

    def _list_identifiers_url(self, resumption_token: str = "") -> str:
        from urllib.parse import urlencode
        if resumption_token:
            return f"{self.oai_endpoint}?{urlencode({'verb': 'ListIdentifiers', 'resumptionToken': resumption_token})}"
        params = {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": self.from_date,
        }
        if self.until_date:
            params["until"] = self.until_date
        if self.oai_set:
            params["set"] = self.oai_set
        return f"{self.oai_endpoint}?{urlencode(params)}"

    def _get_record_url(self, identifier: str) -> str:
        from urllib.parse import urlencode
        return f"{self.oai_endpoint}?{urlencode({'verb': 'GetRecord', 'metadataPrefix': 'oai_dc', 'identifier': identifier})}"

    async def start(self):
        url = self._list_identifiers_url()
        self.logger.info("[OAI ListIdentifiers] %s", url)
        yield scrapy.Request(url=url, callback=self.parse_identifiers, meta={"oai": True})

    def parse_identifiers(self, response):
        """Parse ListIdentifiers page — extract identifiers, yield GetRecord requests."""
        if response.status == 500:
            self.logger.error("OAI ListIdentifiers 500 — server error on endpoint %s", self.oai_endpoint)
            return

        sel = Selector(text=response.text, type="xml")
        for prefix, uri in _NS.items():
            sel.register_namespace(prefix, uri)

        error = sel.xpath("//oai:error/@code").get()
        if error:
            self.logger.warning("OAI error '%s': %s", error, sel.xpath("//oai:error/text()").get() or "")
            return

        identifiers = sel.xpath("//oai:ListIdentifiers/oai:header[not(@status='deleted')]/oai:identifier/text()").getall()
        self.logger.info("[OAI] received %d identifiers in this page", len(identifiers))

        for ident in identifiers:
            if self._accepted >= self.target_limit:
                return
            self._identifiers_fetched += 1
            yield scrapy.Request(
                url=self._get_record_url(ident),
                callback=self.parse_record,
                meta={"identifier": ident},
                priority=5,
            )

        # Pagination
        token = sel.xpath("//oai:ListIdentifiers/oai:resumptionToken/text()").get()
        if token and token.strip() and self._accepted < self.target_limit:
            next_url = self._list_identifiers_url(token.strip())
            yield scrapy.Request(url=next_url, callback=self.parse_identifiers, meta={"oai": True})

    def parse_record(self, response):
        """Parse GetRecord response and yield an item if it passes SC gate."""
        if self._accepted >= self.target_limit:
            return
        if response.status == 500:
            self.logger.debug("GetRecord 500 for %s", response.meta.get("identifier"))
            return

        sel = Selector(text=response.text, type="xml")
        for prefix, uri in _NS.items():
            sel.register_namespace(prefix, uri)

        record = sel.xpath("//oai:GetRecord/oai:record")
        if not record:
            return
        record = record[0]

        if record.xpath("./oai:header/@status").get() == "deleted":
            return

        dc = record.xpath("./oai:metadata/oai_dc:dc")
        if not dc:
            return
        dc = dc[0]

        title = (dc.xpath("./dc:title/text()").get() or "").strip()
        if not title:
            return

        # UNILAG's DSpace OAI-PMH feed has a confirmed server-side encoding
        # bug distinct from anything in this crawler: it replaces non-ASCII
        # bytes (accented/diacritic characters — exactly what shows up in
        # Yoruba names and titles, i.e. precisely the content this platform
        # cares most about preserving correctly) with literal "?" characters
        # in dc:title/dc:creator, even though it declares charset=UTF-8 and
        # despite the SAME record's REST API representation
        # (/api/pid/find?id=hdl:...) having the correct Unicode text. Live-
        # confirmed 2026-07-19 (OAI handle 123456789/13428: OAI feed gives
        # "Ko??la? Aki?nl?d??s", REST gives "Kọ́lá Akínlàdé's" — same item).
        # When detected, re-fetch the clean title from the REST API instead
        # of storing garbled text.
        if _looks_mojibake(title):
            identifier = response.meta.get("identifier", "")
            handle = identifier.rsplit(":", 1)[-1] if ":" in identifier else ""
            if handle and "/" in handle:
                rest_base = self.oai_endpoint.split("/oai/")[0]
                pid_url = f"{rest_base}/api/pid/find?id=hdl:{handle}"
                yield scrapy.Request(
                    url=pid_url,
                    callback=self.parse_record_clean_title,
                    meta={
                        **response.meta,
                        "dc": dc,
                        "corrupted_title": title,
                    },
                    errback=self.errback_clean_title_failed,
                )
                return
            # No usable handle to re-fetch from — can't recover a clean
            # title, and storing known-garbled text directly contradicts
            # this platform's purpose for exactly this kind of content.
            self.logger.warning(
                "OAI mojibake title with no recoverable handle, dropping: %s",
                title[:80],
            )
            return

        yield from self._build_and_yield_item(dc, title)

    def parse_record_clean_title(self, response):
        dc = response.meta["dc"]
        corrupted_title = response.meta["corrupted_title"]
        try:
            clean_title = (response.json() or {}).get("name", "").strip()
        except Exception:
            clean_title = ""
        if not clean_title or _looks_mojibake(clean_title):
            self.logger.warning(
                "OAI mojibake title unrecoverable via REST fallback, dropping: %s",
                corrupted_title[:80],
            )
            return
        self.logger.info(
            "OAI mojibake title repaired via REST: %r -> %r",
            corrupted_title[:60], clean_title[:60],
        )
        yield from self._build_and_yield_item(dc, clean_title)

    def errback_clean_title_failed(self, failure):
        corrupted_title = failure.request.meta.get("corrupted_title", "")
        self.logger.warning(
            "OAI mojibake REST repair request failed, dropping: %s",
            corrupted_title[:80],
        )

    def _build_and_yield_item(self, dc, title):
        creators = [c.strip() for c in dc.xpath("./dc:creator/text()").getall() if c and c.strip()]
        subjects = [s.strip() for s in dc.xpath("./dc:subject/text()").getall() if s and s.strip()]
        descriptions = [d.strip() for d in dc.xpath("./dc:description/text()").getall() if d and d.strip()]
        identifiers = [i.strip() for i in dc.xpath("./dc:identifier/text()").getall() if i and i.strip()]
        dates = [d.strip() for d in dc.xpath("./dc:date/text()").getall() if d and d.strip()]
        rights = [r.strip() for r in dc.xpath("./dc:rights/text()").getall() if r and r.strip()]
        doc_type = (dc.xpath("./dc:type/text()").get() or "").strip()
        languages = [l.strip() for l in dc.xpath("./dc:language/text()").getall() if l and l.strip()]

        url, doi = self._pick_url_and_doi(identifiers)
        pub_date = self._pick_publication_date(dates)
        abstract = max(descriptions, key=len) if descriptions else ""
        # NOTE: dc:description can have the same "?"-corruption as dc:title
        # (see the mojibake handling above) but is deliberately NOT blanked
        # or repaired here. The pipeline (uraas/pipelines/database.py)
        # independently re-runs is_special_collection() on whatever ends up
        # in item["abstract"] as its OWN authoritative gate — blanking a
        # corrupted-but-keyword-rich abstract client-side made that
        # downstream re-check score 0 and silently DropItem a genuine SC
        # paper (live-confirmed regression while developing this fix). A
        # `?`-speckled abstract is a lesser problem than losing the paper
        # entirely; fixing abstract display cleanly needs a fuller REST
        # metadata fetch than pid/find provides, which is future work.
        if sc_score_of(title, abstract, ", ".join(subjects[:8])) <= 0.0:
            return

        # Dedup gate — skip (don't count, but keep paginating past) records
        # already synced from this IR in a prior run.
        if self._is_known(doi=doi, url=url, title=title):
            return

        lang_code = (languages[0].lower() if languages else "") or None

        self._accepted += 1
        item = {
            "title": title,
            "abstract": abstract,
            "authors": creators,
            "authors_full": [{"name": c, "orcid": "", "ror": ""} for c in creators],
            "doi": doi,
            "url": url,
            "pdf_url": None,
            "publication_date": pub_date,
            "source_repository": f"{self.institution_config.short_name} IR (OAI-PMH)",
            "is_own_repository": True,
            "repository_handle": url if "/handle/" in (url or "").lower() else None,
            "is_unilag_author": True,
            "raw_affiliation": self.institution_name,
            "institution": self.institution_name,
            "institution_ror": self.ror_id,
            "dc_subject": ", ".join(subjects[:8]),
            "dc_rights": self._map_rights(rights),
            "content_type": doc_type or None,
            "sdg_tags": None,
            "language_code": lang_code,
            "is_african_language": bool(lang_code and lang_code in AFRICAN_LANG_CODES),
        }
        yield item
        self._mark_seen(doi=doi, url=url, title=title)

    @staticmethod
    def _pick_url_and_doi(identifiers):
        url = ""
        doi = ""
        for ident in identifiers:
            low = ident.lower()
            if "doi.org/" in low or low.startswith("10."):
                doi = ident
            if ident.startswith("http") and not url:
                url = ident
            if "/handle/" in low:
                url = ident
        return url, doi

    @staticmethod
    def _pick_publication_date(dates):
        if not dates:
            return ""
        issued = [d for d in dates if "T" not in d]
        return (issued[0] if issued else dates[-1])

    @staticmethod
    def _map_rights(rights):
        joined = " ".join(rights).lower()
        open_markers = ("creativecommons.org", "cc0", "cc by", "public domain", "open access", "openaccess")
        if any(m in joined for m in open_markers):
            return "info:eu-repo/semantics/openAccess"
        return "info:eu-repo/semantics/restrictedAccess"

    def closed(self, reason):
        self.logger.info(
            "OAI harvester closed: %s | fetched_ids=%d | accepted=%d | "
            "skipped_known=%d (reason=%s)",
            self.institution_name,
            self._identifiers_fetched,
            self._accepted,
            self._skipped_known,
            reason,
        )
