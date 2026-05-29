import os
import sys
from datetime import datetime

import scrapy
from scrapy.http import Request

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS


class ArxivSpider(scrapy.Spider):
    name = "arxiv_multi"
    allowed_domains = ["arxiv.org"]

    def __init__(
        self,
        institution="unilag",
        target=20,
        boost_special=True,
        sc_only=True,
        *args,
        **kwargs,
    ):
        """
        boost_special: fire extra arXiv searches AND-ed with SC seed phrases
                       (default True — heavy SC weight).
        sc_only:       skip the plain institution search; only SC-seeded waves.
        """
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        self.boost_special = str(boost_special).lower() not in (
            "false",
            "0",
            "no",
            "off",
        )
        self.sc_only = str(sc_only).lower() not in ("false", "0", "no", "off")

        # Get institution configuration
        registry = get_registry()
        self.institution_config = registry.get(institution)

        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror

        self.logger.info(f"Initialized ArXiv spider for {self.institution_name}")
        self.logger.info(
            f"ROR ID: {self.ror_id}  | boost_special={self.boost_special} | sc_only={self.sc_only}"
        )

    def _build_url(self, *, extra_term: str = "") -> str:
        import urllib.parse

        encoded_name = urllib.parse.quote(self.institution_name)
        extra = ""
        if extra_term:
            extra_q = urllib.parse.quote(extra_term)
            # terms-1 AND-ed with the institution term-0 (search all fields)
            extra = f"&terms-1-operator=AND&terms-1-term={extra_q}&terms-1-field=all"
        return (
            f"https://arxiv.org/search/advanced?advanced=1"
            f"&terms-0-operator=AND&terms-0-term={encoded_name}&terms-0-field=all"
            f"{extra}"
            f"&date-filter_by=all_dates&date-year=&date-from_date=&date-to_date="
            f"&date-date_type=submitted_date&abstracts=show&size=50&order=-announced_date_first"
        )

    def start_requests(self):
        # Wave 1 — institution-only
        if not self.sc_only:
            url = self._build_url()
            self.logger.info(f"[ROR wave] {url}")
            yield Request(url=url, callback=self.parse, meta={"wave": "ror"})

        # Wave 2 — institution AND each SC seed phrase
        if self.boost_special:
            for seed in SC_SEED_KEYWORDS:
                url = self._build_url(extra_term=seed)
                self.logger.info(f"[SC wave seed={seed!r}] {url}")
                yield Request(
                    url=url,
                    callback=self.parse,
                    meta={"wave": f"sc:{seed}"},
                )

    def parse(self, response):
        # Extract individual paper listings from the search results
        papers = response.css("li.arxiv-result")

        for paper in papers:
            title = paper.css("p.title.is-5.mathjax::text").get(default="").strip()
            authors = paper.css("p.authors a::text").getall()
            abstract = paper.css("span.abstract-full::text").get(default="").strip()

            # The URL to the paper's specific page
            paper_url = paper.css("p.list-title.is-inline-block a::attr(href)").get()
            if paper_url:
                if paper_url.startswith("/"):
                    paper_url = f"https://arxiv.org{paper_url}"

                # Yield request to the paper page to get full affiliations/DOI/pdf
                yield Request(
                    url=paper_url,
                    callback=self.parse_paper,
                    meta={
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "url": paper_url,
                    },
                )

        # Handle pagination
        next_page = response.css("a.pagination-next::attr(href)").get()
        if next_page:
            yield Request(response.urljoin(next_page), callback=self.parse)

    def parse_paper(self, response):
        """Parse individual paper page for detailed metadata."""
        item = response.meta.copy()

        # arXiv doesn't always have explicit affiliation tags easily extractable,
        # but the abstract or comments sometimes mention "University of Lagos".
        # We will parse the raw_text from the whole page as a fallback for the filter pipeline.

        item["doi"] = response.css("td.tablecell.arxivdoi a::text").get()

        # Determine the PDF url
        pdf_link = response.css(
            "div.extra-services ul li a.download-pdf::attr(href)"
        ).get()
        if pdf_link:
            item["pdf_url"] = f"https://arxiv.org{pdf_link}"

        # Get raw text for affiliation matching
        item["raw_affiliation"] = " ".join(
            response.css("div.leftcolumn ::text").getall()
        )
        item["source_repository"] = "arXiv"
        item["is_unilag_author"] = True  # Legacy field
        # NEW: Multi-institution support
        item["institution"] = self.institution_name
        item["institution_ror"] = self.ror_id

        yield item
