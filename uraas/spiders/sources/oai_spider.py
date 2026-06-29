"""
Read-only OAI-PMH harvester for an institution's DSpace repository.

This is the ONLY URAAS spider that talks to an institution's *own* repository
server (e.g. UNILAG's ``api-ir.unilag.edu.ng``). It uses the OAI-PMH protocol,
which is **read-only by specification** — it has no verbs that create, modify, or
delete repository content — so it cannot harm the source repository. It only
issues ``ListRecords`` GETs and follows ``resumptionToken`` pages.

Why this spider exists: the aggregator spiders (OpenAlex/Crossref/arXiv/ORCID)
have broad citation/OA coverage but miss locally-deposited **theses,
dissertations and grey literature** that only live in the institutional
repository. This harvester complements them.

Behaviour notes:
* **Always bounded.** The endpoint is harvested incrementally with ``from`` (and
  optional ``until``). An unbounded full harvest can time out the server, so a
  ``from`` lower bound is always sent (defaulting to a recent look-back window).
* **Polite.** One request at a time, a download delay, AutoThrottle, and a
  contact ``User-Agent`` so the repository admin can identify URAAS traffic.
* **SC-gated downstream.** Like every other source, harvested records flow through
  ``DatabaseStoragePipeline``, which keeps only items the Special-Collections
  classifier scores > 0 — exactly the indigenous-knowledge / cultural-heritage /
  local material the aggregators omit.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import scrapy
from scrapy.selector import Selector

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry

log = logging.getLogger(__name__)

# OAI-PMH XML namespaces.
_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# Default look-back when no from_date is supplied.
# Keep at ~5 years: covers the bulk of active IR deposits without causing 500s
# on DSpace servers that struggle with very large date-range requests.
# For a full back-catalogue harvest, pass --from-date 2000-01-01 explicitly.
_DEFAULT_LOOKBACK_DAYS = 1825  # ~5 years


class OAISpider(scrapy.Spider):
    """Harvest oai_dc metadata from an institution's public OAI-PMH endpoint."""

    name = "oai_repository"
    custom_settings = {
        # Deliberately gentle on the institution's own server.
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 2.0,
        "AUTOTHROTTLE_MAX_DELAY": 15.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": (
            f"URAAS/1.0 (+read-only OAI-PMH harvester; "
            f"mailto:{config.OPENALEX_MAILTO})"
        ),
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
        """
        institution: registry short name; must have ``oai_endpoint`` configured.
        target:      max records to accept this run (hard stop).
        from_date:   lower bound ``YYYY-MM-DD`` (defaults to a recent look-back).
        until_date:  optional upper bound ``YYYY-MM-DD``.
        oai_set:     optional OAI-PMH set spec (e.g. a DSpace community/collection
                     handle like ``com_1234_56``) to filter at source.  When set,
                     only records belonging to that set are returned by the server —
                     drastically reducing traffic for focused harvests.  If None,
                     the institution config's ``oai_set`` field is used if present.
        """
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)

        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.oai_endpoint = self.institution_config.oai_endpoint
        if not self.oai_endpoint:
            raise ValueError(
                f"Institution '{institution}' has no oai_endpoint configured. "
                f"Add it to config/institutions/{institution}.json to enable "
                f"OAI-PMH harvesting."
            )

        # Read by DatabaseStoragePipeline via getattr().
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror

        self.from_date = self._normalize_date(from_date) or self._default_from()
        self.until_date = self._normalize_date(until_date)
        # OAI set: explicit arg > institution config > None (no set filter)
        self.oai_set = (
            oai_set
            or getattr(self.institution_config, "oai_set", None)
            or None
        )

        self._accepted = 0

        self.logger.info(
            "OAI harvester | %s | endpoint=%s | from=%s until=%s | set=%s | target=%d",
            self.institution_name,
            self.oai_endpoint,
            self.from_date,
            self.until_date or "(now)",
            self.oai_set or "(all)",
            self.target_limit,
        )

    # ── URL building ─────────────────────────────────────────────────────────
    @staticmethod
    def _normalize_date(value):
        """Accept YYYY-MM-DD (or full ISO) and return YYYY-MM-DD, else None."""
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        # Keep only the date part; OAI granularity is fine with YYYY-MM-DD.
        return text[:10]

    def _default_from(self) -> str:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        return cutoff.strftime("%Y-%m-%d")

    def _list_records_url(self) -> str:
        from urllib.parse import urlencode

        params = {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc",
            "from": self.from_date,
        }
        if self.until_date:
            params["until"] = self.until_date
        if self.oai_set:
            params["set"] = self.oai_set
        return f"{self.oai_endpoint}?{urlencode(params)}"

    def _resume_url(self, token: str) -> str:
        from urllib.parse import urlencode

        # Per OAI-PMH spec, resumptionToken is sent alone with the verb.
        return f"{self.oai_endpoint}?{urlencode({'verb': 'ListRecords', 'resumptionToken': token})}"

    async def start(self):
        url = self._list_records_url()
        self.logger.info("[OAI ListRecords] %s", url)
        yield scrapy.Request(url=url, callback=self.parse, meta={"oai": True})

    # ── Parsing ──────────────────────────────────────────────────────────────
    def parse(self, response):
        if self._accepted >= self.target_limit:
            return

        # Parse explicitly as XML. OAI-PMH always returns XML, but depending on the
        # Content-Type header Scrapy may otherwise build an HTML selector (which
        # silently fails to match the namespaced OAI/DC nodes).
        sel = Selector(text=response.text, type="xml")
        for prefix, uri in _NS.items():
            sel.register_namespace(prefix, uri)

        # OAI-level error (badArgument, noRecordsMatch, etc.) — log and stop.
        error = sel.xpath("//oai:error/@code").get()
        if error:
            self.logger.warning(
                "OAI error '%s': %s",
                error,
                sel.xpath("//oai:error/text()").get() or "",
            )
            return

        records = sel.xpath("//oai:ListRecords/oai:record")
        self.logger.info("[OAI] received %d records", len(records))

        for record in records:
            if self._accepted >= self.target_limit:
                break

            # Skip deleted records (header status="deleted", no metadata body).
            if record.xpath("./oai:header/@status").get() == "deleted":
                continue

            dc = record.xpath("./oai:metadata/oai_dc:dc")
            if not dc:
                continue
            dc = dc[0]

            title = (dc.xpath("./dc:title/text()").get() or "").strip()
            if not title:
                continue

            creators = [
                c.strip()
                for c in dc.xpath("./dc:creator/text()").getall()
                if c and c.strip()
            ]
            subjects = [
                s.strip()
                for s in dc.xpath("./dc:subject/text()").getall()
                if s and s.strip()
            ]
            descriptions = [
                d.strip()
                for d in dc.xpath("./dc:description/text()").getall()
                if d and d.strip()
            ]
            identifiers = [
                i.strip()
                for i in dc.xpath("./dc:identifier/text()").getall()
                if i and i.strip()
            ]
            dates = [
                d.strip()
                for d in dc.xpath("./dc:date/text()").getall()
                if d and d.strip()
            ]
            rights = [
                r.strip()
                for r in dc.xpath("./dc:rights/text()").getall()
                if r and r.strip()
            ]
            doc_type = (dc.xpath("./dc:type/text()").get() or "").strip()

            url, doi = self._pick_url_and_doi(identifiers)
            pub_date = self._pick_publication_date(dates)
            abstract = max(descriptions, key=len) if descriptions else ""

            self._accepted += 1
            yield {
                "title": title,
                "abstract": abstract,
                "authors": creators,
                "authors_full": [
                    {"name": c, "orcid": "", "ror": ""} for c in creators
                ],
                "doi": doi,
                "url": url,
                "pdf_url": None,  # OAI metadata only; do not fetch IR bitstreams.
                "publication_date": pub_date,
                "source_repository": f"{self.institution_config.short_name} IR (OAI-PMH)",
                "is_unilag_author": True,  # Legacy field expected by pipeline.
                "raw_affiliation": self.institution_name,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                "dc_subject": ", ".join(subjects[:8]),
                "dc_rights": self._map_rights(rights),
                "content_type": doc_type or None,
                "sdg_tags": None,
            }

        # ── Pagination via resumptionToken ───────────────────────────────────
        token = sel.xpath("//oai:ListRecords/oai:resumptionToken/text()").get()
        if token and token.strip() and self._accepted < self.target_limit:
            next_url = self._resume_url(token.strip())
            yield scrapy.Request(url=next_url, callback=self.parse, meta={"oai": True})

    # ── Field helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _pick_url_and_doi(identifiers):
        """From dc:identifier values, pick a landing URL (prefer the Handle) and a DOI."""
        url = ""
        doi = ""
        for ident in identifiers:
            low = ident.lower()
            if "doi.org/" in low or low.startswith("10."):
                doi = ident
            if ident.startswith("http") and not url:
                url = ident
            # Prefer a real handle/landing page over a citation string.
            if "/handle/" in low:
                url = ident
        return url, doi

    @staticmethod
    def _pick_publication_date(dates):
        """Pick the most plausible publication date.

        DSpace emits accessioned/available timestamps plus an 'issued' value
        (often just a year). Prefer a bare year/short date (the issued one) over
        the long accession timestamps.
        """
        if not dates:
            return ""
        # A YYYY or YYYY-MM-DD style value is the issued date; timestamps contain 'T'.
        issued = [d for d in dates if "T" not in d]
        return (issued[0] if issued else dates[-1])

    @staticmethod
    def _map_rights(rights):
        """Map dc:rights to the repo's rights convention.

        Marks clearly-open licences as open access so they aren't needlessly
        gated; everything else stays restricted (the safe default). URAAS stores
        only metadata + the landing URL here, never the IR's bitstreams.
        """
        joined = " ".join(rights).lower()
        open_markers = (
            "creativecommons.org",
            "cc0",
            "cc by",
            "public domain",
            "open access",
            "openaccess",
        )
        if any(m in joined for m in open_markers):
            return "info:eu-repo/semantics/openAccess"
        return "info:eu-repo/semantics/restrictedAccess"

    def closed(self, reason):
        self.logger.info(
            "OAI harvester closed: %s | accepted %d (reason=%s)",
            self.institution_name,
            self._accepted,
            reason,
        )
