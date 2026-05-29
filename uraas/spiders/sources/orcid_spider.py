"""
ORCID Spider - Harvests papers using ORCID IDs from rich staff data.
Loads staff records with ORCID from {inst}_staff.json.
No arbitrary limits — crawls all staff with ORCIDs.
"""

import json
import os
import sys

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from uraas.config.institutions import get_registry


class ORCIDSpider(scrapy.Spider):
    """Harvests papers from ORCID for all staff members with ORCID IDs."""

    name = "orcid_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "CONCURRENT_REQUESTS": 2,
    }

    def __init__(self, institution="unilag", *args, **kwargs):
        super().__init__(*args, **kwargs)
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self.logger.info(
            f"ORCID spider for {self.institution_name} | "
            f"{len(self.institution_config.staff_with_orcid)} staff with ORCIDs"
        )

    def start_requests(self):
        """Query ORCID API for each staff member that has an ORCID."""
        staff_with_orcid = self.institution_config.staff_with_orcid
        if not staff_with_orcid:
            self.logger.warning(
                f"No staff with ORCID IDs found for {self.institution_name}. "
                f"Run scripts/harvest_staff_openalex.py first."
            )
            return

        self.logger.info(f"Querying ORCID API for {len(staff_with_orcid)} researchers")
        for staff_member in staff_with_orcid:
            orcid_id = staff_member["orcid"]
            if not orcid_id:
                continue
            url = f"https://pub.orcid.org/v3.0/{orcid_id}/works"
            yield scrapy.Request(
                url=url,
                callback=self.parse_works,
                headers={"Accept": "application/json"},
                meta={
                    "orcid": orcid_id,
                    "name": staff_member["name"],
                    "department": staff_member.get("department", ""),
                    "faculty": staff_member.get("faculty", ""),
                },
                errback=self.errback_handler,
            )

    def errback_handler(self, failure):
        self.logger.error(f"Request failed: {failure.request.url}")

    def parse_works(self, response):
        """Parse works from ORCID API response."""
        orcid = response.meta["orcid"]
        name = response.meta["name"]
        department = response.meta.get("department", "")
        faculty = response.meta.get("faculty", "")

        try:
            data = response.json()
            works = data.get("group", [])
            self.logger.info(f"Found {len(works)} works for {name} (ORCID: {orcid})")

            for work_group in works:
                work_summary_list = work_group.get("work-summary", [])
                if not work_summary_list:
                    continue
                work = work_summary_list[0]

                title_data = work.get("title", {})
                title = (title_data.get("title", {}) or {}).get("value", "").strip()
                if not title:
                    continue

                # Get DOI from external IDs
                doi = None
                url = None
                for ext_id in (work.get("external-ids", {}) or {}).get(
                    "external-id", []
                ):
                    if ext_id.get("external-id-type") == "doi":
                        doi = ext_id.get("external-id-value", "").strip()
                        if doi:
                            url = f"https://doi.org/{doi}"
                        break

                # Publication date
                pub_date_obj = work.get("publication-date") or {}
                pub_year = (pub_date_obj.get("year", {}) or {}).get("value")
                pub_date = f"{pub_year}-01-01" if pub_year else None

                journal = (work.get("journal-title", {}) or {}).get("value", "")

                yield {
                    "title": title,
                    "authors": [name],
                    "author_orcids": [orcid],
                    "doi": doi,
                    "url": url or f"https://orcid.org/{orcid}",
                    "source_repository": "ORCID",
                    "is_unilag_author": True,  # Legacy field
                    "raw_affiliation": self.institution_name,
                    "orcid": orcid,
                    "publication_date": pub_date,
                    "journal": journal,
                    "abstract": "",
                    "institution": self.institution_name,
                    "institution_ror": self.ror_id,
                    "department": department,
                    "faculty": faculty,
                }
        except Exception as e:
            self.logger.error(f"Error parsing works for {name}: {e}")
