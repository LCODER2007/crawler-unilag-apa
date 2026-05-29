import scrapy
from scholarly import scholarly, ProxyGenerator
import uuid
import time
import random
import os
import sys
import json

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config.institutions import get_registry
from uraas.config.special_collections import all_classifier_keywords


class ScholarSpider(scrapy.Spider):
    name = "scholar_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 5.0,
    }

    def __init__(self, institution="unilag", *args, **kwargs):
        """
        Initialize spider with institution parameter

        Args:
            institution: Short name or ROR ID of institution (default: 'unilag')
        """
        super().__init__(*args, **kwargs)

        # Get institution configuration
        registry = get_registry()
        self.institution_config = registry.get(institution)

        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror

        self.logger.info(f"Initialized Scholar spider for {self.institution_name}")
        self.logger.info(f"ROR ID: {self.ror_id}")

    def start_requests(self):
        # Set up free proxy rotation to avoid Google IP blocks
        try:
            pg = ProxyGenerator()
            pg.FreeProxies()
            scholarly.use_proxy(pg)
            self.logger.info("ScholarSpider: ProxyGenerator active.")
        except Exception as e:
            self.logger.warning(
                f"ScholarSpider: Could not set up proxy ({e}). Proceeding without proxy."
            )

        yield scrapy.Request(url="data:,", callback=self.fetch_scholarly)

    def fetch_scholarly(self, response):
        # Load staff names from institution config
        staff_names = self.institution_config.staff_names

        self.logger.info(
            f"ScholarSpider: Loaded {len(staff_names)} staff names for {self.institution_name}"
        )

        if staff_names:
            # Targeted search for actual faculty members
            targets = random.sample(staff_names, min(len(staff_names), 5))
            for name in targets:
                self.logger.info(f"ScholarSpider: Searching for faculty member: {name}")
                query = scholarly.search_author(f"{name}, {self.institution_name}")
                yield from self._process_author_query(query)
                time.sleep(random.uniform(5, 10))  # Polite delay
        else:
            # Fallback to generic institutional search
            self.logger.info(
                f"ScholarSpider: No staff cache found. Performing generic search for {self.institution_name}"
            )
            query = scholarly.search_author(self.institution_name)
            yield from self._process_author_query(query)

    def _process_author_query(self, query):
        # We process a limited number of results from the query
        try:
            for _ in range(5):  # Extract up to 5 authors per page for more volume
                author = next(query)
                author = scholarly.fill(author)
                profile_name = author.get("name", "Unknown")
                publications = author.get("publications", [])

                for pub in publications[:10]:  # Up to 10 papers per author
                    pub_filled = scholarly.fill(pub)
                    bib = pub_filled.get("bib", {})
                    abstract = bib.get("abstract", "")
                    title = bib.get("title", "")
                    if not title:
                        continue

                    combined = f"{title} {abstract}".lower()
                    kws = all_classifier_keywords()
                    if not any(kw.lower() in combined for kw in kws):
                        self.logger.debug(
                            f"ScholarSpider: Skipping non-SC paper: {title[:50]}"
                        )
                        continue

                    authors_str = bib.get("author", "")
                    authors_list = (
                        [a.strip() for a in authors_str.split(" and ")]
                        if authors_str
                        else [profile_name]
                    )

                    yield {
                        "title": title,
                        "abstract": bib.get("abstract", ""),
                        "authors": authors_list,
                        "doi": "",
                        "pdf_url": pub_filled.get("eprint_url", ""),
                        "url": pub_filled.get("pub_url", "")
                        or f"https://scholar.google.com/#id={uuid.uuid4()}",
                        "source_repository": "Google Scholar",
                        "is_unilag_author": True,  # Legacy field
                        "raw_affiliation": self.institution_name,
                        # NEW: Multi-institution support
                        "institution": self.institution_name,
                        "institution_ror": self.ror_id,
                    }
        except StopIteration:
            pass
        except Exception as e:
            self.logger.error(f"ScholarSpider: Error processing author ({e})")
