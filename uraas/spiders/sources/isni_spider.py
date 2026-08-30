"""
ISNI Spider - Looks up ISNI (International Standard Name Identifier) records
for institution staff by name via the public ISNI SRU search API.

This is identity enrichment, not a paper source: it writes directly onto
existing Author rows (Author.isni) via SessionLocal and does NOT yield
pipeline items, so it must not be routed through DatabaseStoragePipeline
(that pipeline requires a "title" and gates on Special-Collections score,
neither of which applies to an identifier lookup).

The SRU API's isni-b response is NOT well-formed XML: each <record> element
is left unclosed and its payload is the *inner* ISNI record HTML-entity
-escaped as text (verified against a live response), e.g.:

    <record>&lt;responseRecord&gt;&lt;ISNIAssigned&gt;
      &lt;isniUnformatted&gt;0000000122774961&lt;/isniUnformatted&gt;
    ...  (no closing </record> tag at all)

A strict XML parser chokes on this, so parsing is done with html.unescape()
+ regex against the raw response text instead of an XML/XPath parser.

Personal-name ISNI records rarely carry a queryable institutional
affiliation field, so false-positive name collisions (common names) can't
be reliably ruled out via an organisation-name check. Instead: only
auto-attach an ISNI when the search returns exactly one candidate record;
ambiguous (multi-candidate) responses are skipped rather than guessed at.

Publisher-level ISNI is intentionally out of scope: there is no Publisher
model/field anywhere in the schema yet for it to attach to.
"""

import html
import os
import re
import sys
import urllib.parse

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config.institutions import get_registry
from uraas.database import Author, SessionLocal

_ISNI_RE = re.compile(r"<isniUnformatted>\s*(\d{15}[\dXx])\s*</isniUnformatted>")
_NUM_RECORDS_RE = re.compile(
    r"<(?:\w+:)?numberOfRecords>\s*(\d+)\s*</(?:\w+:)?numberOfRecords>"
)


class ISNISpider(scrapy.Spider):
    """Looks up ISNI identifiers for institution staff by name."""

    name = "isni_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS": 1,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "USER_AGENT": "URAAS/1.0 (+read-only ISNI SRU lookup)",
    }

    def __init__(self, institution="unilag", *args, **kwargs):
        super().__init__(*args, **kwargs)
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._matched = 0
        self._checked = 0

    async def start(self):
        staff = self.institution_config.staff_records
        if not staff:
            self.logger.warning(f"No staff records found for {self.institution_name}")
            return

        self.logger.info(
            f"Looking up ISNI for {len(staff)} staff at {self.institution_name}"
        )
        for staff_member in staff:
            name = staff_member.get("name")
            if not name:
                continue
            query = urllib.parse.quote(f'pica.nw="{name}"')
            url = (
                "https://isni.oclc.org/sru/DB=1.2/CQL?"
                f"query={query}&recordSchema=isni-b&maximumRecords=5"
            )
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={"name": name},
                errback=self.errback_handler,
            )

    def errback_handler(self, failure):
        self.logger.warning(f"ISNI lookup failed: {failure.request.url}")

    def parse(self, response):
        name = response.meta["name"]
        self._checked += 1

        try:
            raw = response.text
            num_match = _NUM_RECORDS_RE.search(raw)
            num_records = int(num_match.group(1)) if num_match else None

            # Unescape once — the payload inside <record> is HTML-entity-escaped
            # inner XML text, not real child elements (see module docstring).
            unescaped = html.unescape(raw)
            candidates = list(dict.fromkeys(_ISNI_RE.findall(unescaped)))

            if not candidates:
                return

            if num_records == 1 or len(candidates) == 1:
                isni_value = candidates[0]
            else:
                # Ambiguous — multiple distinct ISNI candidates for a common
                # name and no reliable affiliation field to disambiguate with.
                self.logger.debug(
                    f"ISNI ambiguous for {name!r}: {len(candidates)} candidates, skipping"
                )
                return
        except Exception as e:
            self.logger.debug(f"ISNI parse error for {name}: {e}")
            return

        session = SessionLocal()
        try:
            author = (
                session.query(Author)
                .filter_by(normalized_name=name.lower().strip())
                .first()
            )
            if author and not author.isni:
                author.isni = isni_value
                session.commit()
                self._matched += 1
                self.logger.info(f"ISNI matched: {name} -> {isni_value}")
        except Exception as e:
            self.logger.error(f"Error saving ISNI for {name}: {e}")
            session.rollback()
        finally:
            session.close()

    def closed(self, reason):
        self.logger.info(
            f"ISNI spider closed | {self.institution_name} | "
            f"checked={self._checked} | matched={self._matched} | reason={reason}"
        )
