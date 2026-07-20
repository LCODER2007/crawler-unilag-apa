"""
ORCID Spider — harvests papers using ORCID IDs from rich staff data.
Loads staff records with ORCID from {inst}_staff.json.

Precision design: ORCID work-summary records carry NO institutional
affiliation at all (that's an ORCID schema limitation — affiliation lives
under /employments, not /works), so a naive "everything this ORCID ever
published belongs to <institution>" crawl mis-attributes a researcher's
entire pre-/post-<institution> publication history. Before pulling a
person's works we fetch /employments once and, when it lists the target
institution, use the employment start/end date to only accept works
published while they were actually there. When ORCID lists employment(s)
at OTHER institutions only (no match for the target), we drop the person's
works rather than blindly attributing them — this catches stale
institution assignments (e.g. someone whose ROR-authorship snapshot from
one paper got them added to the staff roster, but who has since moved).
When a person has no employment history on ORCID at all (common — many
researchers never fill this in), we fall back to trusting the static
roster assignment, since there's no contradicting signal.
"""

import os
import sys

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin


class ORCIDSpider(DedupAwareSpiderMixin, scrapy.Spider):
    """Harvests papers from ORCID for all staff members with ORCID IDs."""

    name = "orcid_multi"
    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "CONCURRENT_REQUESTS": 2,
    }

    def __init__(self, institution="unilag", target=20, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self.max_results_scanned = config.MAX_RESULTS_SCANNED

        self._accepted = 0
        self._rejected_no_employment_match = 0
        self._rejected_outside_employment_dates = 0
        self._unverified_no_employment_data = 0

        self.logger.info(
            f"ORCID spider for {self.institution_name} | "
            f"{len(self.institution_config.staff_with_orcid)} staff with ORCIDs | "
            f"target={self.target_limit}"
        )
        self._init_dedup_index()

    async def start(self):
        """First fetch /employments for each staff member (to verify institution
        affiliation + get a date range), then their /works."""
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
            yield scrapy.Request(
                url=f"https://pub.orcid.org/v3.0/{orcid_id}/employments",
                callback=self.parse_employments,
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

    def parse_employments(self, response):
        orcid = response.meta["orcid"]
        name = response.meta["name"]

        target_matched = False
        had_any_employment = False
        orcid_department = None
        start_years = []
        end_years = []
        ongoing = False

        try:
            data = response.json()
            for group in data.get("affiliation-group", []):
                for summary in group.get("summaries", []):
                    es = summary.get("employment-summary", {})
                    if not es:
                        continue
                    had_any_employment = True
                    org_name = (es.get("organization") or {}).get("name", "")
                    if not org_name or not self.institution_config.matches_affiliation(
                        org_name
                    ):
                        continue
                    target_matched = True
                    sd = (es.get("start-date") or {}).get("year", {}).get("value")
                    ed = (es.get("end-date") or {}).get("year", {}).get("value")
                    if sd:
                        start_years.append(int(sd))
                    # Merge across multiple stints at the same institution —
                    # any stint still open (no end-date) means "currently
                    # employed" wins over any other, older, closed stint.
                    if ed:
                        end_years.append(int(ed))
                    else:
                        ongoing = True
                    if es.get("department-name"):
                        orcid_department = es["department-name"]
        except Exception as e:
            self.logger.debug(f"Could not parse employments for {name} ({orcid}): {e}")

        if had_any_employment and not target_matched:
            # ORCID positively lists employment(s) elsewhere and none at the
            # target institution — the roster assignment for this person is
            # very likely stale/wrong. Skip their works entirely rather than
            # mis-attribute them.
            self._rejected_no_employment_match += 1
            self.logger.info(
                f"ORCID SKIP (no employment match): {name} ({orcid}) - "
                f"ORCID lists employment elsewhere, not at {self.institution_name}"
            )
            return

        if not had_any_employment:
            self._unverified_no_employment_data += 1

        year_start = min(start_years) if start_years else None
        year_end = 0 if ongoing else (max(end_years) if end_years else None)

        meta = dict(response.meta)
        meta["employment_year_start"] = year_start
        meta["employment_year_end"] = year_end  # None=no target match info, 0=ongoing
        meta["orcid_department"] = orcid_department
        yield scrapy.Request(
            url=f"https://pub.orcid.org/v3.0/{orcid}/works",
            callback=self.parse_works,
            headers={"Accept": "application/json"},
            meta=meta,
            errback=self.errback_handler,
        )

    def parse_works(self, response):
        """Parse works from ORCID API response."""
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        orcid = response.meta["orcid"]
        name = response.meta["name"]
        department = response.meta.get("department", "") or response.meta.get(
            "orcid_department", ""
        )
        faculty = response.meta.get("faculty", "")
        year_start = response.meta.get("employment_year_start")
        year_end = response.meta.get("employment_year_end")

        try:
            data = response.json()
            works = data.get("group", [])
            self.logger.info(f"Found {len(works)} works for {name} (ORCID: {orcid})")

            for work_group in works:
                if self._accepted >= self.target_limit:
                    break
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

                # Date-bound against the verified employment window, when we
                # have one. year_end == 0 means "still employed" (open-ended).
                if year_start is not None and pub_year:
                    try:
                        pub_year_int = int(pub_year)
                        if pub_year_int < year_start or (
                            year_end not in (None, 0) and pub_year_int > year_end
                        ):
                            self._rejected_outside_employment_dates += 1
                            continue
                    except ValueError:
                        pass

                journal = (work.get("journal-title", {}) or {}).get("value", "")

                # SC gate — only count papers the storage pipeline will keep,
                # so `target` means "N genuinely new SC papers" (same
                # discipline as every other web-discovery spider).
                if sc_score_of(title, "", journal) <= 0.0:
                    continue

                if self._is_known(doi=doi, url=url, title=title):
                    continue

                self._accepted += 1
                item = {
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
                yield item
                self._mark_seen(doi=doi, url=url, title=title)
        except Exception as e:
            self.logger.error(f"Error parsing works for {name}: {e}")

    def closed(self, reason):
        self.logger.info(
            f"ORCID spider closed | {self.institution_name} | "
            f"accepted={self._accepted} | "
            f"skipped_known={self._skipped_known} | "
            f"rejected_no_employment_match={self._rejected_no_employment_match} | "
            f"rejected_outside_employment_dates={self._rejected_outside_employment_dates} | "
            f"unverified_no_employment_data={self._unverified_no_employment_data} | "
            f"reason={reason}"
        )
